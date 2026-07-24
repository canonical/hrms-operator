# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the charm upgrade path."""

import logging
from urllib.parse import urlparse

import jubilant

from integration.constants import UPGRADE_TIMEOUT
from integration.helpers import (
    all_settled,
    assert_url_serves_ok,
    get_gateway_address,
    get_ingress_url,
)

logger = logging.getLogger(__name__)


def test_upgrade_from_charmhub_to_local(
    juju: jubilant.Juju,
    charmhub_hrms: str,
    charm_path: str,
    resource_images: dict[str, str],
    gateway_api_integrator: str,
) -> None:
    """
    arrange: HRMS deployed from Charmhub at the latest published revision.
    act: Refresh the charm to the locally-packed version.
    assert: The charm reaches active/idle and the ingress URL returns HTTP 200.
    """
    app = charmhub_hrms

    logger.info("Refreshing %s from Charmhub revision to local charm at %s", app, charm_path)

    juju.refresh(
        app,
        path=charm_path,
        resources=resource_images,
    )

    juju.wait(all_settled, timeout=UPGRADE_TIMEOUT)
    logger.info("Upgrade successful: %s is active", app)

    # Verify the HRMS web interface is reachable via ingress after upgrade.
    ingress_url = get_ingress_url(juju, app)
    assert ingress_url, "Ingress URL not found in the HRMS ingress relation databag"
    parsed = urlparse(ingress_url)
    assert parsed.hostname, f"Ingress URL {ingress_url!r} has no hostname"

    gateway_address = get_gateway_address(juju, gateway_api_integrator)
    assert gateway_address, "Gateway address not found in gateway-api-integrator status message"

    logger.info(
        "Checking HRMS webpage at %s (resolved to gateway %s)", ingress_url, gateway_address
    )
    assert_url_serves_ok(ingress_url, parsed.hostname, gateway_address)
