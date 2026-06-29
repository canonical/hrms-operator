#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the Frappe HRMS charm.

These tests deploy frappe-hrms together with mariadb-k8s, redis-k8s, and
traefik-k8s and verify that all charms reach active/idle and the HRMS
webpage is reachable through the Traefik ingress URL.
"""

import logging

import jubilant
import pytest
import requests

logger = logging.getLogger(__name__)

MARIADB_APP = "mariadb-k8s"
REDIS_APP = "redis-k8s"
TRAEFIK_APP = "traefik-k8s"
FRAPPE_APP = "frappe-hrms"
SITE_NAME = "frappe-hrms"
ADMIN_PASSWORD = "TestPass123!"

# Frappe site creation (bench new-site + install erpnext + install hrms) can
# take up to 20 minutes on a freshly provisioned cluster.
DEPLOY_TIMEOUT = 30 * 60


@pytest.mark.abort_on_fail
def test_deploy(charm: str, frappe_hrms_image: str, juju: jubilant.Juju):
    """
    arrange: An empty Juju K8s model.
    act: Deploy frappe-hrms alongside mariadb-k8s, redis-k8s, and traefik-k8s
         and wire up all integrations.
    assert: All applications reach active/idle within the timeout.
    """
    juju.deploy(MARIADB_APP, channel="latest/edge", trust=True)
    juju.deploy(REDIS_APP, channel="latest/edge", trust=True)
    juju.deploy(TRAEFIK_APP, channel="latest/stable", trust=True)
    juju.deploy(
        charm,
        app=FRAPPE_APP,
        config={"site-name": SITE_NAME, "admin-password": ADMIN_PASSWORD},
        resources={"hrms-image": frappe_hrms_image},
        trust=True,
    )

    juju.integrate(f"{FRAPPE_APP}:mysql", f"{MARIADB_APP}:database")
    juju.integrate(f"{FRAPPE_APP}:redis", f"{REDIS_APP}:redis")
    juju.integrate(f"{FRAPPE_APP}:ingress", f"{TRAEFIK_APP}:ingress")

    juju.wait(
        lambda s: jubilant.all_active(s) and jubilant.all_agents_idle(s),
        timeout=DEPLOY_TIMEOUT,
    )


@pytest.mark.abort_on_fail
def test_all_active_idle(juju: jubilant.Juju):
    """
    arrange: All charms deployed and integrated.
    act: Query Juju status.
    assert: Every application is active and every unit agent is idle.
    """
    status = juju.status()
    for app_name in [FRAPPE_APP, MARIADB_APP, REDIS_APP, TRAEFIK_APP]:
        app = status.apps[app_name]
        assert app.is_active, (
            f"{app_name} app status is {app.app_status.current!r}: {app.app_status.message}"
        )
        for unit_name, unit in app.units.items():
            assert unit.juju_status.current == "idle", (
                f"{unit_name} agent is {unit.juju_status.current!r}: {unit.juju_status.message}"
            )


@pytest.mark.abort_on_fail
def test_webpage_accessible(juju: jubilant.Juju):
    """
    arrange: All charms active/idle, Traefik ingress configured.
    act: HTTP GET the ingress URL for the HRMS app.
    assert: The response is not a server error (< 500), confirming the
            Frappe frontend is reachable through the ingress.
    """
    status = juju.status()

    # Prefer app-level address (K8s LoadBalancer IP) then fall back to pod IP.
    traefik_address = status.apps[TRAEFIK_APP].address
    if not traefik_address:
        traefik_units = status.apps[TRAEFIK_APP].units
        if traefik_units:
            unit = next(iter(traefik_units.values()))
            traefik_address = unit.public_address or unit.address
    assert traefik_address, "Could not determine Traefik address from status"

    model_name = juju.model or "test"
    url = f"http://{traefik_address}/{model_name}-{FRAPPE_APP}"

    logger.info("Checking HRMS webpage at %s", url)
    response = requests.get(url, allow_redirects=True, timeout=30)
    logger.info("Response: %s %s", response.status_code, response.url)
    assert response.status_code < 500, (
        f"Expected non-5xx response from {url}, got HTTP {response.status_code}"
    )
