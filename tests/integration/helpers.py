# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared helpers for the Frappe HRMS integration tests."""

import ipaddress
import json
import typing
from urllib.parse import urlparse

import jubilant
import requests
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed


class DNSResolverHTTPSAdapter(requests.adapters.HTTPAdapter):
    """A requests transport adapter that routes a hostname to a fixed IP.

    Lets ``requests`` connect to a known IP while sending the correct SNI and
    Host header, which hostname-scoped Gateway listeners require.
    """

    def __init__(self, hostname: str, ip: str) -> None:
        self.hostname = hostname
        self.ip = ip
        super().__init__()

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: typing.Any = None,
        proxies: typing.Mapping[str, str] | None = None,
    ) -> requests.Response:
        connection_pool_kwargs = self.poolmanager.connection_pool_kw
        url = request.url
        if url is not None:
            result = urlparse(url)
            if result.hostname == self.hostname:
                if result.scheme == "https" and self.ip:
                    request.url = url.replace(
                        "https://" + self.hostname,
                        "https://" + self.ip,
                    )
                    connection_pool_kwargs["server_hostname"] = self.hostname
                    connection_pool_kwargs["assert_hostname"] = self.hostname
                    request.headers["Host"] = self.hostname
                else:
                    connection_pool_kwargs.pop("server_hostname", None)
                    connection_pool_kwargs.pop("assert_hostname", None)
        return super().send(request, stream, timeout, verify, cert, proxies)


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
def assert_url_serves_ok(url: str, hostname: str, ip: str) -> None:
    """Assert that the ingress URL returns HTTP 200 when resolved to the gateway IP."""
    session = requests.Session()
    session.mount("https://", DNSResolverHTTPSAdapter(hostname, ip))
    response = session.get(url, verify=False, timeout=10)  # nosec B501
    assert response.status_code == 200, f"Expected HTTP 200 from {url}, got {response.status_code}"
