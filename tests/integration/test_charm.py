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
    juju.deploy(
        TRAEFIK_APP,
        channel="latest/stable",
        config={"routing_mode": "subdomain", "external_hostname": "hrms.local"},
        trust=True,
    )
    juju.deploy(
        charm,
        app=FRAPPE_APP,
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
    arrange: All charms active/idle, Traefik ingress configured with subdomain routing.
    act: HTTP GET the ingress URL published in the ingress relation data.
    assert: The response is not a server error (< 500), confirming the
            Frappe frontend is reachable through the ingress.
    """
    import json as json_mod

    # Read the ingress URL from the relation data published by Traefik.
    output = juju.cli("show-unit", "--format", "json", f"{FRAPPE_APP}/0")
    unit_data = json_mod.loads(output)[f"{FRAPPE_APP}/0"]

    url = None
    for rel in unit_data.get("relation-info", []):
        if rel.get("endpoint") == "ingress":
            app_data = rel.get("application-data", {})
            ingress_raw = app_data.get("ingress", "")
            if ingress_raw:
                ingress_parsed = json_mod.loads(ingress_raw)
                url = ingress_parsed.get("url")
            break

    assert url, "Ingress URL not found in relation data"
    logger.info("Checking HRMS webpage at %s", url)

    # Resolve the ingress hostname to the Traefik unit address since the
    # external_hostname is not DNS-resolvable in CI.
    from urllib.parse import urlparse

    parsed = urlparse(url)
    status = juju.status()
    traefik_units = status.apps[TRAEFIK_APP].units
    traefik_ip = next(iter(traefik_units.values())).address
    direct_url = f"{parsed.scheme}://{traefik_ip}:{parsed.port or 80}{parsed.path}"

    response = requests.get(
        direct_url,
        headers={"Host": parsed.hostname},
        allow_redirects=True,
        timeout=30,
    )
    logger.info("Response: %s %s", response.status_code, response.url)
    assert response.status_code < 500, (
        f"Expected non-5xx response from {url}, got HTTP {response.status_code}"
    )


@pytest.mark.abort_on_fail
def test_get_admin_credentials(juju: jubilant.Juju):
    """
    arrange: HRMS charm is active with a created site.
    act: Run the get-admin-credentials action.
    assert: The action returns a username and a non-empty password.
    """
    task = juju.run(f"{FRAPPE_APP}/leader", "get-admin-credentials")
    assert task.results["username"] == "Administrator"
    assert len(task.results["password"]) > 0
    logger.info("Admin credentials retrieved successfully")


def test_create_user(juju: jubilant.Juju):
    """
    arrange: HRMS charm is active with a created site.
    act: Run the create-user action with an email and first name.
    assert: The action succeeds and returns the email and a password.
    """
    task = juju.run(
        f"{FRAPPE_APP}/leader",
        "create-user",
        {"email": "testuser@example.com", "first-name": "Test", "last-name": "User"},
    )
    assert task.results["email"] == "testuser@example.com"
    assert len(task.results["password"]) > 0
    logger.info("User created successfully: %s", task.results["email"])
