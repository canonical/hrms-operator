# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures and shared helpers for the unit tests."""

from scenario import Container, Exec, Relation, Secret

CONTAINER = "frappe-hrms"
BENCH = "/home/frappe/frappe-bench"


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


def make_container(
    *,
    site_exists: bool = False,
    installed_apps_output: str = "frappe\nerpnext\nhrms\n",
) -> Container:
    return Container(
        CONTAINER,
        can_connect=True,
        execs=make_execs(
            site_exists=site_exists,
            installed_apps_output=installed_apps_output,
        ),
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
