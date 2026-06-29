#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS Kubernetes Charm."""

import logging
import re

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
HTTP_PORT = 8080


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

        admin_password = str(self.config.get("admin-password", "")).strip()
        if not admin_password:
            self.unit.status = ops.BlockedStatus("Required config 'admin-password' is not set")
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
                self.unit.status = ops.WaitingStatus("Initialising Frappe site")
                workload.create_site(state)

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
    # Private helpers
    # ------------------------------------------------------------------

    def _derive_db_name(self) -> str:
        """Derive a database name from the site-name config or app name."""
        site_name = str(self.config.get("site-name", "")).strip()
        if site_name:
            return re.sub(r"[.\-]", "_", site_name)
        return re.sub(r"[.\-]", "_", self.app.name)


if __name__ == "__main__":  # pragma: nocover
    ops.main(HRMSCharm)
