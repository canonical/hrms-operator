#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the Frappe HRMS COS integrations."""

import logging

import jubilant

from integration.constants import (
    FRAPPE_APP,
    GRAFANA_APP,
    LOKI_APP,
    PROMETHEUS_APP,
)

logger = logging.getLogger(__name__)

COS_TIMEOUT = 20 * 60


def test_cos_integrations(juju: jubilant.Juju, frappe_hrms: str) -> None:
    """
    arrange: HRMS deployed and active with its dependencies.
    act: Deploy Prometheus, Loki, and Grafana and integrate each with HRMS.
    assert: All applications settle into active/idle with the relations formed.
    """
    juju.deploy(PROMETHEUS_APP, channel="1/stable", trust=True)
    juju.deploy(LOKI_APP, channel="1/stable", trust=True)
    juju.deploy(GRAFANA_APP, channel="1/stable", trust=True)

    juju.integrate(f"{frappe_hrms}:metrics-endpoint", f"{PROMETHEUS_APP}:metrics-endpoint")
    juju.integrate(f"{frappe_hrms}:logging", f"{LOKI_APP}:logging")
    juju.integrate(f"{frappe_hrms}:grafana-dashboard", f"{GRAFANA_APP}:grafana-dashboard")

    juju.wait(
        lambda status: jubilant.all_active(
            status, FRAPPE_APP, PROMETHEUS_APP, LOKI_APP, GRAFANA_APP
        ),
        timeout=COS_TIMEOUT,
        delay=10,
    )

    status = juju.status()
    hrms_relations = {
        endpoint
        for app in status.apps.values()
        for unit in app.units.values()
        for endpoint in getattr(unit, "relation_info", [])
    }
    logger.info("HRMS relations after COS integration: %s", hrms_relations)
