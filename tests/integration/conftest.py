# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for the integration tests."""

import jubilant
import pytest

from integration.constants import (
    CERTIFICATES_APP,
    EXTERNAL_HOSTNAME,
    FRAPPE_APP,
    GATEWAY_APP,
    GATEWAY_CLASS,
    INGRESS_CONFIGURATOR_APP,
    MARIADB_APP,
    VALKEY_APP,
)
from integration.helpers import all_settled

DEPLOY_TIMEOUT = 10 * 60


@pytest.fixture(scope="module", name="admin_password_secret")
def admin_password_secret_fixture(juju: jubilant.Juju) -> str:
    """Create a Juju secret holding the HRMS admin password."""
    return juju.add_secret("admin-password-secret", {"password": "test-admin-password"})


@pytest.fixture(scope="module", name="mariadb")
def mariadb_fixture(juju: jubilant.Juju) -> str:
    """Deploy mariadb-k8s."""
    juju.deploy(MARIADB_APP, channel="latest/edge", trust=True)
    return MARIADB_APP


@pytest.fixture(scope="module", name="valkey")
def valkey_fixture(juju: jubilant.Juju) -> str:
    """Deploy valkey."""
    juju.deploy(VALKEY_APP, channel="9/edge", trust=True)
    return VALKEY_APP


@pytest.fixture(scope="module", name="certificates")
def certificates_fixture(juju: jubilant.Juju) -> str:
    """Deploy self-signed-certificates."""
    juju.deploy(CERTIFICATES_APP, channel="1/stable", trust=True)
    return CERTIFICATES_APP


@pytest.fixture(scope="module", name="gateway_api_integrator")
def gateway_api_integrator_fixture(juju: jubilant.Juju, certificates: str) -> str:
    """Deploy gateway-api-integrator with a TLS certificate provider."""
    juju.deploy(
        GATEWAY_APP,
        channel="1/stable",
        base="ubuntu@24.04",
        config={"gateway-class": GATEWAY_CLASS},
        trust=True,
    )
    juju.integrate(f"{GATEWAY_APP}:certificates", f"{certificates}:certificates")
    return GATEWAY_APP


@pytest.fixture(scope="module", name="ingress_configurator")
def ingress_configurator_fixture(
    juju: jubilant.Juju,
    gateway_api_integrator: str,
) -> str:
    """Deploy ingress-configurator."""
    juju.deploy(
        INGRESS_CONFIGURATOR_APP,
        channel="latest/edge",
        base="ubuntu@24.04",
        config={"hostname": EXTERNAL_HOSTNAME},
        trust=True,
    )
    juju.integrate(f"{gateway_api_integrator}:gateway-route", INGRESS_CONFIGURATOR_APP)
    return INGRESS_CONFIGURATOR_APP


@pytest.fixture(scope="module", name="frappe_hrms")
def frappe_hrms_fixture(
    juju: jubilant.Juju,
    charm_path: str,
    resource_images: dict[str, str],
    admin_password_secret: str,
    mariadb: str,
    valkey: str,
    ingress_configurator: str,
) -> str:
    """Deploy frappe-hrms, integrate its dependencies, and wait for active/idle."""
    juju.deploy(
        charm_path,
        app=FRAPPE_APP,
        resources=resource_images,
        config={"admin-password-secret": admin_password_secret},
        trust=True,
    )
    juju.grant_secret(admin_password_secret, FRAPPE_APP)

    juju.integrate(f"{FRAPPE_APP}:database", f"{mariadb}:database")
    juju.integrate(f"{FRAPPE_APP}:valkey", f"{valkey}:valkey-client")
    juju.integrate(f"{FRAPPE_APP}:ingress", f"{ingress_configurator}:ingress")

    juju.wait(all_settled, timeout=DEPLOY_TIMEOUT)
    return FRAPPE_APP
