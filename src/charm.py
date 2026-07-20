#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS Kubernetes Charm."""

import logging
import typing

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.redis_k8s.v0.redis import RedisRelationCharmEvents, RedisRequires
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from pydantic import ValidationError

from state import (
    CharmState,
    InvalidConfigError,
    InvalidIntegrationError,
    MissingConfigError,
    MissingIntegrationError,
)
from workload import FrappeWorkload

logger = logging.getLogger(__name__)

CONTAINER_NAME = "frappe-hrms"
DATABASE_RELATION = "database"
REDIS_RELATION = "redis"
INGRESS_RELATION = "ingress"
PEER_RELATION = "hrms-peers"
HTTP_PORT = 8080
METRICS_PORT = 9102


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

        self._metrics_endpoint = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{METRICS_PORT}"]}]}],
            refresh_event=[
                self.on.config_changed,
                self.on[CONTAINER_NAME].pebble_ready,
            ],
        )
        self._grafana_dashboards = GrafanaDashboardProvider(
            self,
            relation_name="grafana-dashboard",
        )
        self._logging = LogForwarder(self, relation_name="logging")

        for event in [
            self.on[CONTAINER_NAME].pebble_ready,
            self.on[CONTAINER_NAME].pebble_check_failed,
            self.on[CONTAINER_NAME].pebble_check_recovered,
            self.on.config_changed,
            self.on.update_status,
            self._database.on.database_created,
            self._database.on.endpoints_changed,
            self.on.redis_relation_updated,
            self._ingress.on.ready,
            self._ingress.on.revoked,
        ]:
            self.framework.observe(event, self._reconcile)

    def _reconcile(self, _: ops.EventBase) -> None:
        """Reconcile the workload with the desired state."""
        self._container = self.unit.get_container(CONTAINER_NAME)
        if not self._container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for Pebble to be ready")
            return

        try:
            state = CharmState.from_charm(self, self._database, self._redis)
        except (
            MissingIntegrationError,
            InvalidIntegrationError,
            MissingConfigError,
            InvalidConfigError,
            ValidationError,
        ):
            self.unit.status = ops.BlockedStatus("Invalid charm state; check the debug logs")
            logger.exception("Failed to build charm state")
            return

        workload = FrappeWorkload(self._container)
        workload.setup_assets()
        apps_ready = workload.required_apps_installed()
        if not apps_ready:
            self.unit.status = ops.MaintenanceStatus("Setting up HRMS")
            workload.setup_hrms(state)

        config_changed = workload.configure(state)
        workload.reconcile_services(restart=config_changed)

        if workload.services_healthy():
            self.unit.status = ops.ActiveStatus()
        else:
            self.unit.status = ops.WaitingStatus("Waiting for services to become healthy")


if __name__ == "__main__":  # pragma: nocover
    ops.main(HRMSCharm)
