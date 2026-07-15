# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures and shared helpers for the unit tests."""

from unittest import mock

import pytest
from dpcharmlibs.interfaces import ValkeyResponseModel
from ops import pebble
from scenario import CheckInfo, Container, Exec, Relation, Secret

from state import CharmState

CONTAINER = "frappe-hrms"
BENCH = "/home/frappe/frappe-bench"

CHECK_LAYER = pebble.Layer(
    {
        "checks": {
            "frontend-ready": {"override": "replace", "level": "ready", "tcp": {"port": 8080}},
            "backend-up": {"override": "replace", "tcp": {"port": 8000}},
            "websocket-up": {"override": "replace", "tcp": {"port": 9000}},
        },
    }
)


def make_execs(
    *,
    site_exists: bool = False,
    installed_apps_output: str = "frappe\nerpnext\nhrms\n",
) -> frozenset:
    return frozenset(
        {
            Exec(["chown"], return_code=0),
            Exec(["test", "-f"], return_code=0 if site_exists else 1),
            Exec([f"{BENCH}/env/bin/bench", "new-site"], return_code=0, stdout="Site created"),
            Exec(
                [f"{BENCH}/env/bin/bench", "--site"], return_code=0, stdout=installed_apps_output
            ),
            Exec(["rm"], return_code=0),
        }
    )


def make_check_infos(*, frontend_up: bool = True) -> frozenset:
    """Return CheckInfos for the container, optionally marking frontend down."""
    frontend_status = pebble.CheckStatus.UP if frontend_up else pebble.CheckStatus.DOWN
    return frozenset(
        {
            CheckInfo("frontend-ready", level=pebble.CheckLevel.READY, status=frontend_status),
            CheckInfo("backend-up"),
            CheckInfo("websocket-up"),
        }
    )


def make_container(
    *,
    site_exists: bool = False,
    installed_apps_output: str = "frappe\nerpnext\nhrms\n",
    checks_healthy: bool = True,
) -> Container:
    return Container(
        CONTAINER,
        can_connect=True,
        execs=make_execs(
            site_exists=site_exists,
            installed_apps_output=installed_apps_output,
        ),
        layers={"checks": CHECK_LAYER},
        check_infos=make_check_infos(frontend_up=checks_healthy),
    )


def make_database_relation(
    *,
    host: str = "mariadb-host",
    port: int = 3306,
    user: str = "frappe_user",
    password: str = "db-password",
    database: str = "hrms_db",
) -> Relation:
    return Relation(
        "database",
        remote_app_name="mariadb-k8s",
        remote_app_data={
            "endpoints": f"{host}:{port}",
            "username": user,
            "password": password,
            "database": database,
        },
    )


def make_valkey_relation() -> Relation:
    return Relation(
        "valkey",
        remote_app_name="valkey",
    )


def make_valkey_response(
    *,
    host: str = "valkey-host",
    port: int = 6379,
    endpoints: str | None = None,
    username: str = "hrms",
    password: str = "valkey-pass",
    tls: bool = False,
) -> ValkeyResponseModel:
    return ValkeyResponseModel(
        resource="*",
        endpoints=endpoints if endpoints is not None else f"{host}:{port}",
        username=username,
        password=password,
        tls=tls,
    )


@pytest.fixture(autouse=True)
def valkey_ready():
    """Make the Valkey integration report a ready response by default.

    The valkey_client data contract stores credentials in Juju secrets, which is
    impractical to reproduce in Scenario, so tests patch the response fetch seam.
    Negative tests override this by patching ``_fetch_valkey_responses`` again.
    """
    with mock.patch.object(
        CharmState, "_fetch_valkey_responses", return_value=[make_valkey_response()]
    ):
        yield


def make_admin_secret(password: str | None = None) -> Secret:
    """Return a Secret fixture containing an admin password."""
    return Secret({"password": password or "test-admin-password"})
