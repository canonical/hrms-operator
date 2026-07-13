# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared helpers for the Frappe HRMS integration tests."""

import ipaddress
import json

import jubilant
import requests
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed


def all_settled(status: jubilant.Status) -> bool:
    """Return True when all applications are active and all agents are idle."""
    return jubilant.all_active(status) and jubilant.all_agents_idle(status)


def get_ingress_url(juju: jubilant.Juju, app: str) -> str:
    """Return the ingress URL published to the app through its ingress relation databag."""
    output = juju.cli("show-unit", "--format", "json", f"{app}/0")
    unit_data = json.loads(output)[f"{app}/0"]
    for relation in unit_data.get("relation-info", []):
        if relation.get("endpoint") == "ingress":
            ingress_raw = relation.get("application-data", {}).get("ingress", "")
            if ingress_raw:
                return str(json.loads(ingress_raw).get("url", ""))
    return ""


def get_gateway_address(juju: jubilant.Juju, gateway_app: str) -> str:
    """Return the gateway LB address published in the gateway-api-integrator status message."""
    status = juju.status()
    message = status.apps[gateway_app].app_status.message
    if "gateway address" in message.lower():
        parts = message.split()
        try:
            candidate = parts[2]
            ipaddress.IPv4Address(candidate)
            return candidate
        except (IndexError, ipaddress.AddressValueError):
            return ""
    return ""


@retry(
    stop=stop_after_delay(180),
    wait=wait_fixed(5),
    retry=retry_if_exception_type((requests.exceptions.RequestException, AssertionError)),
    reraise=True,
)
def assert_url_serves_ok(url: str, hostname: str) -> None:
    """Assert if the URL returns HTTP 200."""
    response = requests.get(url, headers={"Host": hostname}, verify=False, timeout=10)
    assert response.status_code == 200, f"Expected HTTP 200 from {url}, got {response.status_code}"
