# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the Frappe HRMS charm."""

import logging
from urllib.parse import urlparse

import jubilant

from integration.helpers import (
    assert_url_serves_ok,
    get_gateway_address,
    get_ingress_url,
)

logger = logging.getLogger(__name__)


def test_webpage_accessible(
    juju: jubilant.Juju, frappe_hrms: str, gateway_api_integrator: str
) -> None:
    """
    arrange: HRMS deployed and integrated with its dependencies.
    act: Run HTTPS GET on the ingress URL.
    assert: The ingress URL returns HTTP 200 OK.
    """
    ingress_url = get_ingress_url(juju, frappe_hrms)
    assert ingress_url, "Ingress URL not found in the HRMS ingress relation databag"
    parsed = urlparse(ingress_url)
    assert parsed.hostname, f"Ingress URL {ingress_url!r} has no hostname"

    gateway_address = get_gateway_address(juju, gateway_api_integrator)
    assert gateway_address, "Gateway address not found in gateway-api-integrator status message"

    logger.info(
        "Checking HRMS webpage at %s (resolved to gateway %s)", ingress_url, gateway_address
    )

    assert_url_serves_ok(ingress_url, parsed.hostname, gateway_address)
