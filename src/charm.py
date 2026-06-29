# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS Kubernetes Charm.

Implements the holistic (reconciler) pattern: every interesting Juju event
is routed to :meth:`FrappeHRMSCharm._reconcile`, which reads all state,
computes the desired world, and writes it out. No ``defer`` is used.

Architecture:
  * ``state.py``    - runtime state abstraction (CharmState, Pydantic)
  * ``workload.py`` - all pebble / exec interactions (FrappeWorkload)
  * ``charm.py``    - Juju event wiring and orchestration (this file)

Relations:
  * ``mysql``      (requires) - MariaDB via data-platform-libs
  * ``redis``      (requires) - Redis via redis-k8s lib
  * ``ingress``    (requires) - Traefik ingress via traefik-k8s lib
"""

import logging

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


class FrappeHRMSCharm(ops.CharmBase):
    """Charm for deploying Frappe HRMS on Kubernetes."""

    on = RedisRelationCharmEvents()  # type: ignore[assignment]

    def __init__(self, framework: ops.Framework) -> None:
        """Initialise the charm, wiring up all event handlers."""
        super().__init__(framework)

        self._container = self.unit.get_container(CONTAINER_NAME)

        # Integration helpers -------------------------------------------------
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

        # Holistic event subscription ----------------------------------------
        # All events that may change charm state are routed to _reconcile.
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

        # upgrade-charm is handled separately (runs migration)
        framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Status collection
        framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

        # Expose the HTTP port so Juju/Kubernetes knows what port to open
        self.unit.set_ports(ops.Port("tcp", HTTP_PORT))

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def _reconcile(self, _: ops.EventBase) -> None:
        """Reconcile the workload with the desired state.

        Reads all state, delegates configuration to FrappeWorkload,
        creates the Frappe site on first run, and (re)starts services.
        """
        if not self._container.can_connect():
            return

        if not self._prerequisites_ready():
            return

        try:
            state = CharmState.from_charm(self, self._database, self._redis, self._ingress)
        except (InvalidConfigError, MissingRelationError) as exc:
            # Status reported via _on_collect_unit_status; no action here.
            logger.debug("Prerequisites not satisfied: %s", exc)
            return

        workload = FrappeWorkload(self._container)

        try:
            workload.setup_assets()
            config_changed = workload.configure(state)

            site_just_created = False
            if not workload.site_exists(state.site_name):
                workload.create_site(state)
                site_just_created = True

            if config_changed and not site_just_created:
                workload.restart_services()
            else:
                workload.start_services()

        except WorkloadError:
            logger.exception("Workload reconciliation failed")

    # ------------------------------------------------------------------
    # Upgrade (refresh) handler
    # ------------------------------------------------------------------

    def _on_upgrade_charm(self, _: ops.UpgradeCharmEvent) -> None:
        """Run bench migrate and restart services after an OCI image upgrade.

        The sites/ directory is ephemeral (no PVC is defined).  On every pod
        restart the directory is empty and the site is recreated from scratch
        by ``_reconcile``.  Therefore this handler only runs the migration if
        the site is already present; otherwise ``_reconcile`` will handle the
        full site creation on the next event.
        """
        if not self._container.can_connect():
            return

        if not self._prerequisites_ready():
            return

        try:
            state = CharmState.from_charm(self, self._database, self._redis, self._ingress)
        except (InvalidConfigError, MissingRelationError) as exc:
            logger.warning("Cannot run upgrade migration: %s", exc)
            return

        workload = FrappeWorkload(self._container)

        if not workload.site_exists(state.site_name):
            # Site will be (re)created by the next _reconcile call.
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
        except WorkloadError:
            logger.exception("Upgrade migration failed")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the current unit status.

        All conditions are evaluated independently; ops selects the most
        severe status from all that are added (Blocked > Waiting > Active).
        We return early only when subsequent checks require pebble access.
        """
        # Config checks do not require pebble - evaluate first so that a
        # missing config is reported as Blocked even when pebble is not yet up.
        site_name = str(self.config.get("site-name", "")).strip()
        if not site_name:
            event.add_status(ops.BlockedStatus("Required config 'site-name' is not set"))

        admin_password = str(self.config.get("admin-password", "")).strip()
        if not admin_password:
            event.add_status(ops.BlockedStatus("Required config 'admin-password' is not set"))

        if not self._container.can_connect():
            event.add_status(ops.WaitingStatus("Waiting for Pebble to be ready"))
            # Cannot check workload or relation state without pebble; stop here.
            return

        if not self._database.is_resource_created():
            event.add_status(ops.BlockedStatus(f"Waiting for '{DATABASE_RELATION}' integration"))

        if not self._redis.url:
            event.add_status(ops.BlockedStatus(f"Waiting for '{REDIS_RELATION}' integration"))

        if site_name:
            workload = FrappeWorkload(self._container)
            if not workload.site_exists(site_name):
                event.add_status(ops.WaitingStatus("Initialising Frappe site"))

        event.add_status(ops.ActiveStatus())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prerequisites_ready(self) -> bool:
        """Return True if the minimum prerequisites for reconciliation are met."""
        return (
            self._container.can_connect()
            and bool(str(self.config.get("site-name", "")).strip())
            and bool(str(self.config.get("admin-password", "")).strip())
            and self._database.is_resource_created()
            and bool(self._redis.url)
        )

    def _derive_db_name(self) -> str:
        """Derive a database name from the site-name config or app name."""
        import re

        site_name = str(self.config.get("site-name", "")).strip()
        if site_name:
            return re.sub(r"[.\-]", "_", site_name)
        return re.sub(r"[.\-]", "_", self.app.name)


if __name__ == "__main__":  # pragma: nocover
    ops.main(FrappeHRMSCharm)
