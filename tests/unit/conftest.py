# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures and shared helpers for the unit tests."""

from pathlib import Path
from typing import Optional

import pytest
from scenario import Container, Exec, Mount, Relation, Secret

CONTAINER = "frappe-hrms"
BENCH = "/home/frappe/frappe-bench"

_NGINX_TEMPLATE = (
    "server { server_name FRAPPE_SERVER_NAME; "
    "proxy_read_timeout PROXY_READ_TIMEOUT; "
    "client_max_body_size CLIENT_MAX_BODY_SIZE; "
    "add_header X-Frappe-Site FRAPPE_SITE_NAME_HEADER; }"
)


@pytest.fixture
def templates_path(tmp_path: Path) -> Path:
    """Create a tmp dir with the nginx config template pre-populated."""
    nginx_dir = tmp_path / "nginx"
    nginx_dir.mkdir()
    (nginx_dir / "frappe.conf.template").write_text(_NGINX_TEMPLATE)
    return tmp_path


def make_execs(
    *,
    site_exists: bool = False,
    installed_apps_output: str = "frappe\nerpnext\nhrms\n",
) -> frozenset:
    return frozenset(
        {
            Exec(["chown"], return_code=0),
            Exec(["ln", "-sfn"], return_code=0),
            Exec(["test", "-f"], return_code=0 if site_exists else 1),
            Exec([f"{BENCH}/env/bin/bench", "new-site"], return_code=0, stdout="Site created"),
            Exec(
                [f"{BENCH}/env/bin/bench", "--site"], return_code=0, stdout=installed_apps_output
            ),
            Exec(["rm"], return_code=0),
        }
    )


def make_container(
    *,
    site_exists: bool = False,
    installed_apps_output: str = "frappe\nerpnext\nhrms\n",
    templates_path: Optional[Path] = None,
) -> Container:
    mounts = (
        {"templates": Mount(location="/templates", source=templates_path)}
        if templates_path is not None
        else {}
    )
    return Container(
        CONTAINER,
        can_connect=True,
        execs=make_execs(
            site_exists=site_exists,
            installed_apps_output=installed_apps_output,
        ),
        mounts=mounts,
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


def make_redis_relation(*, host: str = "redis-host", port: int = 6379) -> Relation:
    return Relation(
        "redis",
        remote_app_name="redis-k8s",
        remote_units_data={0: {"hostname": host, "port": str(port)}},
    )


def make_admin_secret(password: str | None = None) -> Secret:
    """Return a Secret fixture containing an admin password."""
    return Secret({"password": password or "test-admin-password"})
