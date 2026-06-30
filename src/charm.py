#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS Kubernetes Charm."""

import logging
import re
import secrets
import string

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.redis_k8s.v0.redis import RedisRelationCharmEvents, RedisRequires
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

from state import CharmState, InvalidConfigError, MissingRelationError
from workload import FrappeWorkload, WorkloadError

logger = logging.getLogger(__name__)

CONTAINER_NAME = "frappe-hrms"
DATABASE_RELATION = "mysql"
REDIS_RELATION = "redis"
INGRESS_RELATION = "ingress"
PEER_RELATION = "hrms-peers"
HTTP_PORT = 8080
_PASSWORD_LENGTH = 24


class HRMSCharm(ops.CharmBase):
    """Charm for deploying Frappe HRMS on Kubernetes."""

    on = RedisRelationCharmEvents()  # type: ignore[assignment]

    def __init__(self, framework: ops.Framework) -> None:
        """Initialise the charm, wiring up all event handlers."""
        super().__init__(framework)

        self._container = self.unit.get_container(CONTAINER_NAME)

        self._database = DatabaseRequires(
            self,
            relation_name=DATABASE_RELATION,
            database_name=self._derive_db_name(),
        )
        self._redis = RedisRequires(self, REDIS_RELATION)
        self._ingress = IngressPerAppRequirer(
            self,
            relation_name=INGRESS_RELATION,
            port=HTTP_PORT,
            strip_prefix=True,
        )

        for event in [
            self.on[CONTAINER_NAME].pebble_ready,
            self.on.config_changed,
            self._database.on.database_created,
            self._database.on.endpoints_changed,
            self.on.redis_relation_updated,
            self._ingress.on.ready,
            self._ingress.on.revoked,
        ]:
            framework.observe(event, self._reconcile)

        framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        framework.observe(self.on.get_admin_credentials_action, self._on_get_admin_credentials)
        framework.observe(self.on.create_user_action, self._on_create_user)

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def _reconcile(self, _: ops.EventBase) -> None:
        """Reconcile the workload with the desired state."""
        # Config checks come first — report errors even when pebble is not ready.
        site_name = str(self.config.get("site-name", "")).strip()
        if not site_name:
            self.unit.status = ops.BlockedStatus("Required config 'site-name' is not set")
            return

        if not self._container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for Pebble to be ready")
            return

        if not self._database.is_resource_created():
            self.unit.status = ops.BlockedStatus(f"Waiting for '{DATABASE_RELATION}' integration")
            return

        if not self._redis.url:
            self.unit.status = ops.BlockedStatus(f"Waiting for '{REDIS_RELATION}' integration")
            return

        try:
            state = CharmState.from_charm(self, self._database, self._redis, self._ingress)
        except (InvalidConfigError, MissingRelationError) as exc:
            self.unit.status = ops.BlockedStatus(str(exc))
            return

        workload = FrappeWorkload(self._container)

        try:
            workload.setup_assets()
            config_changed = workload.configure(state)

            if not workload.site_exists(state.site_name):
                admin_password = self._get_or_generate_admin_password()
                self.unit.status = ops.WaitingStatus("Initialising Frappe site")
                workload.create_site(state, admin_password)

            if config_changed:
                workload.restart_services()
            else:
                workload.start_services()

            self.unit.status = ops.ActiveStatus()

        except WorkloadError as exc:
            self.unit.status = ops.BlockedStatus(str(exc))
            logger.exception("Workload reconciliation failed")

    # ------------------------------------------------------------------
    # Upgrade (refresh) handler
    # ------------------------------------------------------------------

    def _on_upgrade_charm(self, _: ops.UpgradeCharmEvent) -> None:
        """Run bench migrate and restart services after an OCI image upgrade."""
        if not self._container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for Pebble to be ready")
            return

        try:
            state = CharmState.from_charm(self, self._database, self._redis, self._ingress)
        except (InvalidConfigError, MissingRelationError) as exc:
            self.unit.status = ops.BlockedStatus(str(exc))
            return

        workload = FrappeWorkload(self._container)

        if not workload.site_exists(state.site_name):
            logger.info(
                "Site %r not yet ready; skipping upgrade migration (will be created by reconcile)",
                state.site_name,
            )
            return

        try:
            workload.setup_assets()
            workload.configure(state)
            workload.migrate(state.site_name)
            workload.restart_services()
            self.unit.status = ops.ActiveStatus()
        except WorkloadError as exc:
            self.unit.status = ops.BlockedStatus(str(exc))
            logger.exception("Upgrade migration failed")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_get_admin_credentials(self, event: ops.ActionEvent) -> None:
        """Return the auto-generated admin credentials."""
        password = self._get_admin_password()
        if not password:
            event.fail("Admin credentials not yet available (site not created)")
            return

        event.set_results({"username": "Administrator", "password": password})

    def _on_create_user(self, event: ops.ActionEvent) -> None:
        """Create a new user on the Frappe site."""
        if not self._container.can_connect():
            event.fail("Pebble is not ready")
            return

        site_name = str(self.config.get("site-name", "")).strip()
        if not site_name:
            event.fail("site-name config is not set")
            return

        workload = FrappeWorkload(self._container)
        if not workload.site_exists(site_name):
            event.fail("Frappe site has not been created yet")
            return

        email = str(event.params["email"])
        first_name = str(event.params["first-name"])
        last_name = str(event.params.get("last-name", ""))
        password = str(event.params.get("password", ""))
        role = str(event.params.get("role", ""))

        if not password:
            password = self._generate_password()

        try:
            workload.create_user(
                site_name=site_name,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
                role=role,
            )
        except WorkloadError as exc:
            event.fail(str(exc))
            return

        event.set_results({"email": email, "password": password})

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_generate_admin_password(self) -> str:
        """Return the stored admin password, generating one if needed."""
        password = self._get_admin_password()
        if password:
            return password

        password = self._generate_password()
        peer_rel = self.model.get_relation(PEER_RELATION)
        if peer_rel and self.unit.is_leader():
            peer_rel.data[self.app]["admin-password"] = password
        return password

    def _get_admin_password(self) -> str:
        """Read the admin password from peer relation data."""
        peer_rel = self.model.get_relation(PEER_RELATION)
        if not peer_rel:
            return ""
        return peer_rel.data[self.app].get("admin-password", "")

    @staticmethod
    def _generate_password() -> str:
        """Generate a secure random password."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(_PASSWORD_LENGTH))

    def _derive_db_name(self) -> str:
        """Derive a database name from the site-name config or app name."""
        site_name = str(self.config.get("site-name", "")).strip()
        if site_name:
            return re.sub(r"[.\-]", "_", site_name)
        return re.sub(r"[.\-]", "_", self.app.name)


if __name__ == "__main__":  # pragma: nocover
    ops.main(HRMSCharm)
