#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS Kubernetes Charm."""

import logging
import typing

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.redis_k8s.v0.redis import RedisRelationCharmEvents, RedisRequires
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

from state import CharmState, MissingRelationError
from workload import FrappeWorkload, WorkloadError

logger = logging.getLogger(__name__)

CONTAINER_NAME = "frappe-hrms"
DATABASE_RELATION = "mariadb"
REDIS_RELATION = "redis"
INGRESS_RELATION = "ingress"
PEER_RELATION = "hrms-peers"
HTTP_PORT = 8080


class HRMSCharm(ops.CharmBase):
    """Frappe HRMS charm."""

    on = RedisRelationCharmEvents()  # type: ignore[assignment]

    def __init__(self, *args: typing.Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the charm base.
        """
        super().__init__(*args)

        self._database = DatabaseRequires(
            self,
            relation_name=DATABASE_RELATION,
            database_name=self.app.name,
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
            self.on[CONTAINER_NAME].pebble_check_failed,
            self.on.config_changed,
            self.on.update_status,
            self._database.on.database_created,
            self._database.on.endpoints_changed,
            self.on.redis_relation_updated,
            self._ingress.on.ready,
            self._ingress.on.revoked,
        ]:
            self.framework.observe(event, self._reconcile)

        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_dependencies(self) -> ops.StatusBase | None:
        """Check if all required relations are ready.

        Returns a BlockedStatus if any dependency is missing, None if all ready.
        """
        if not self._database.is_resource_created():
            return ops.BlockedStatus(f"Waiting for '{DATABASE_RELATION}' integration")

        if not self._redis.url:
            return ops.BlockedStatus(f"Waiting for '{REDIS_RELATION}' integration")

        return None

    def _get_charm_state(self) -> CharmState | None:
        """Get the current charm state.

        Returns the state if successful, sets status and returns None if not.
        """
        try:
            state = CharmState.from_charm(self, self._database, self._redis, self._ingress)
        except MissingRelationError as exc:
            self.unit.status = ops.BlockedStatus(str(exc))
            return None

        return state

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def _reconcile(self, _: ops.EventBase) -> None:
        """Reconcile the workload with the desired state."""
        self._container = self.unit.get_container(CONTAINER_NAME)
        if not self._container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for Pebble to be ready")
            return

        # Check dependencies and return early if not ready
        status = self._check_dependencies()
        if status is not None:
            self.unit.status = status
            return

        state = self._get_charm_state()
        if state is None:
            return

        workload = FrappeWorkload(self._container)

        try:
            workload.setup_assets()

            # Create site if it doesn't exist yet
            if not workload.site_exists(state.site_name):
                if not state.admin_password:
                    self.unit.status = ops.BlockedStatus(
                        "Set 'admin-password-secret' config before initialising the site"
                    )
                    return
                self.unit.status = ops.WaitingStatus("Initialising Frappe site")
                workload.create_site(state, state.admin_password)
                return  # Let the next reconcile handle configuration

            # Now that the site is ready, push the pebble layer and start services.
            config_changed = workload.configure(state)

            if config_changed:
                workload.restart_services()
            else:
                workload.start_services()

            # Check if all services are healthy before declaring active.
            # If health checks are failing, stay in waiting status.
            if workload.services_healthy():
                self.unit.status = ops.ActiveStatus()
            else:
                self.unit.status = ops.WaitingStatus("Waiting for services to become healthy")

        except WorkloadError as exc:
            self.unit.status = ops.BlockedStatus(str(exc))
            logger.exception("Workload reconciliation failed")

    def _on_upgrade_charm(self, _: ops.UpgradeCharmEvent) -> None:
        """Run bench migrate and restart services after an OCI image upgrade."""
        self._container = self.unit.get_container(CONTAINER_NAME)
        if not self._container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for Pebble to be ready")
            return

        try:
            state = CharmState.from_charm(self, self._database, self._redis, self._ingress)
        except MissingRelationError as exc:
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


if __name__ == "__main__":  # pragma: nocover
    ops.main(HRMSCharm)
