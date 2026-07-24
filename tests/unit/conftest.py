# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures and shared helpers for the unit tests."""

from ops import pebble
from scenario import CheckInfo, Container, Exec, Relation, Secret

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

# Default version info for tests - versions match so no migration needed
# bench version --format json returns a list of {app, version, branch, commit}
DEFAULT_DISK_VERSIONS = (
    '[{"app": "frappe", "version": "16.0.0"}, '
    '{"app": "erpnext", "version": "16.0.0"}, '
    '{"app": "hrms", "version": "16.0.0"}]'
)
# Disk versions with drift (16.0.1) - triggers migration
DRIFTED_DISK_VERSIONS = (
    '[{"app": "frappe", "version": "16.0.1"}, '
    '{"app": "erpnext", "version": "16.0.1"}, '
    '{"app": "hrms", "version": "16.0.1"}]'
)
# Default list-apps output with versions (format: "app version branch")
DEFAULT_LIST_APPS_OUTPUT = (
    "frappe 16.0.0 version-16\nerpnext 16.0.0 version-16\nhrms 16.0.0 version-16\n"
)


def make_execs(
    *,
    site_exists: bool = False,
    installed_apps_output: str = DEFAULT_LIST_APPS_OUTPUT,
    disk_versions: str = DEFAULT_DISK_VERSIONS,
    migrate_return_code: int = 0,
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
            Exec(
                [
                    f"{BENCH}/env/bin/bench",
                    "--site",
                    "frappe-hrms",
                    "version",
                    "--format",
                    "json",
                ],
                return_code=0,
                stdout=disk_versions,
            ),
            Exec(
                [f"{BENCH}/env/bin/bench", "--site", "frappe-hrms", "migrate"],
                return_code=migrate_return_code,
            ),
            Exec(
                [f"{BENCH}/env/bin/bench", "--site", "frappe-hrms", "set-maintenance-mode"],
                return_code=0,
            ),
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
    installed_apps_output: str = DEFAULT_LIST_APPS_OUTPUT,
    disk_versions: str = DEFAULT_DISK_VERSIONS,
    migrate_return_code: int = 0,
    checks_healthy: bool = True,
) -> Container:
    return Container(
        CONTAINER,
        can_connect=True,
        execs=make_execs(
            site_exists=site_exists,
            installed_apps_output=installed_apps_output,
            disk_versions=disk_versions,
            migrate_return_code=migrate_return_code,
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


def make_redis_relation(*, host: str = "redis-host", port: int = 6379) -> Relation:
    return Relation(
        "redis",
        remote_app_name="redis-k8s",
        remote_units_data={0: {"hostname": host, "port": str(port)}},
    )


def make_admin_secret(password: str | None = None) -> Secret:
    """Return a Secret fixture containing an admin password."""
    return Secret({"password": password or "test-admin-password"})
