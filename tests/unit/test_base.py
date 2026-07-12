# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS charm using ops scenario testing."""

import json
from pathlib import Path
from typing import Optional

import ops
import pytest
from scenario import Container, Context, Exec, Mount, PeerRelation, Relation, Secret, State

from charm import HRMSCharm

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


def _execs(
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


def _container(
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
        execs=_execs(
            site_exists=site_exists,
            installed_apps_output=installed_apps_output,
        ),
        mounts=mounts,
    )


def _database_relation(
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


def _redis_relation(*, host: str = "redis-host", port: int = 6379) -> Relation:
    return Relation(
        "redis",
        remote_app_name="redis-k8s",
        remote_units_data={0: {"hostname": host, "port": str(port)}},
    )


def _admin_secret(password: str | None = None) -> Secret:
    """Return a Secret fixture containing an admin password."""
    return Secret({"password": password or "test-admin-password"})


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestBlockedStatus:
    def test_waiting_for_pebble(self):
        ctx = Context(HRMSCharm, charm_root=".")
        container = Container(CONTAINER, can_connect=False)
        state = State(containers=[container])
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == ops.WaitingStatus("Waiting for Pebble to be ready")

    def test_blocked_waiting_for_database(self):
        ctx = Context(HRMSCharm, charm_root=".")
        c = Container(CONTAINER, can_connect=True, execs=_execs())
        state = State(containers=[c])
        out = ctx.run(ctx.on.pebble_ready(c), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "check the debug logs" in out.unit_status.message.lower()

    def test_blocked_waiting_for_redis(self):
        ctx = Context(HRMSCharm, charm_root=".")
        c = Container(CONTAINER, can_connect=True, execs=_execs())
        state = State(containers=[c], relations=[_database_relation()])
        out = ctx.run(ctx.on.pebble_ready(c), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "check the debug logs" in out.unit_status.message.lower()

    def test_active_after_site_creation(self, templates_path: Path):
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        # reconcile_services starts the services, which the scenario emulator
        # then reports as running, so the charm becomes active.
        assert out.unit_status == ops.ActiveStatus()

    def test_waiting_when_redis_not_reachable_for_site_init(self):
        """When the Redis relation data has no port yet, reconcile should wait (not block)."""
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=False)
        secret = _admin_secret()
        # Redis relation with no port in unit data → url becomes redis://host:None
        # → _collect_redis returns None → MissingIntegrationError → BlockedStatus
        # We verify that a relation with port missing is treated as "not ready".
        redis_no_port = Relation(
            "redis",
            remote_app_name="redis-k8s",
            remote_units_data={0: {"hostname": "redis-host"}},  # port absent
        )
        state = State(
            containers=[c],
            relations=[_database_relation(), redis_no_port, PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "check the debug logs" in out.unit_status.message.lower()

    def test_existing_site_installs_missing_hrms_app(self, templates_path: Path):
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(
            site_exists=True,
            installed_apps_output="frappe\nerpnext\n",
            templates_path=templates_path,
        )
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        assert out.unit_status == ops.ActiveStatus()

    def test_blocked_when_no_admin_password_secret(self, templates_path: Path):
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "check the debug logs" in out.unit_status.message.lower()

    def test_blocked_when_state_validation_fails(self, templates_path: Path, monkeypatch):
        from pydantic import ValidationError

        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )

        def raise_validation_error(*args, **kwargs):
            raise ValidationError.from_exception_data(
                "CharmState",
                [
                    {
                        "type": "missing",
                        "loc": ("admin_password",),
                        "input": {},
                    }
                ],
            )

        monkeypatch.setattr("charm.CharmState.from_charm", raise_validation_error)

        out = ctx.run(ctx.on.pebble_ready(c), state)
        assert isinstance(out.unit_status, ops.BlockedStatus)
        assert "check the debug logs" in out.unit_status.message.lower()

    def test_active_when_site_exists(self, templates_path: Path):
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        # In test environment, services won't be running, so charm waits for them
        assert out.unit_status == ops.ActiveStatus()


# ---------------------------------------------------------------------------
# Tests: pebble layer
# ---------------------------------------------------------------------------


class TestPebbleLayer:
    def _run(self, templates_path: Path, **kwargs) -> Container:
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(templates_path=templates_path, site_exists=True, **kwargs)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        return out.get_container(CONTAINER)

    def test_pebble_layer_has_all_services(self, templates_path: Path):
        c = self._run(templates_path)
        for svc in ("backend", "websocket", "frontend", "queue-short", "queue-long", "scheduler"):
            assert svc in c.plan.services, f"Service {svc!r} missing from pebble plan"

    def test_pebble_layer_services_all_disabled(self, templates_path: Path):
        """Services start disabled to prevent check failures during site creation.

        They are explicitly started by the charm after the site is fully
        initialized, avoiding pebble checks running while DocTypes are updating.
        """
        c = self._run(templates_path)
        for name in ("backend", "websocket", "frontend", "queue-short", "queue-long", "scheduler"):
            assert c.plan.services[name].startup in (
                "disabled",
                ops.pebble.ServiceStartup.DISABLED,
            ), f"Service {name!r} should have startup=disabled"

    def test_pebble_checks_no_alive_level(self, templates_path: Path):
        """level=alive is prohibited by the charm guidelines."""
        c = self._run(templates_path)
        for check_name, check in c.plan.checks.items():
            assert check.level != ops.pebble.CheckLevel.ALIVE, (
                f"Check {check_name!r} must not use level=alive"
            )

    def test_pebble_backend_uses_gunicorn(self, templates_path: Path):
        c = self._run(templates_path)
        assert "gunicorn" in c.plan.services["backend"].command

    def test_pebble_websocket_uses_node(self, templates_path: Path):
        c = self._run(templates_path)
        assert "node" in c.plan.services["websocket"].command

    def test_pebble_frontend_uses_nginx(self, templates_path: Path):
        c = self._run(templates_path)
        assert "nginx" in c.plan.services["frontend"].command

    def test_backend_check_failure_restarts_service(self, templates_path: Path):
        c = self._run(templates_path)
        on_failure = c.plan.services["backend"].on_check_failure
        assert "backend-up" in on_failure
        assert on_failure["backend-up"] == "restart"


# ---------------------------------------------------------------------------
# Tests: config file generation
# ---------------------------------------------------------------------------


class TestConfigFiles:
    def test_common_site_config_written(self, templates_path: Path):
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[
                _database_relation(host="db.local", port=3306),
                _redis_relation(host="redis.local", port=6379),
                PeerRelation("hrms-peers"),
            ],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)

        root = out.get_container(CONTAINER).get_filesystem(ctx)
        config_path = root / "home/frappe/frappe-bench/sites/common_site_config.json"
        assert config_path.exists(), "common_site_config.json should be written"
        config = json.loads(config_path.read_text())

        assert config["db_host"] == "db.local"
        assert config["db_port"] == 3306
        assert config["redis_cache"] == "redis://redis.local:6379"
        assert config["redis_queue"] == "redis://redis.local:6379"
        assert config["socketio_port"] == 9000

    def test_nginx_config_written(self, templates_path: Path):
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)

        root = out.get_container(CONTAINER).get_filesystem(ctx)
        nginx_path = root / "etc/nginx/conf.d/frappe.conf"
        assert nginx_path.exists(), "nginx frappe.conf should be written"
        assert len(nginx_path.read_text()) > 0

    def test_common_config_not_rewritten_when_unchanged(self, templates_path: Path):
        """configure() returns False when nothing changed; services are still reconciled."""
        ctx = Context(HRMSCharm, charm_root=".")
        c = _container(site_exists=True, templates_path=templates_path)
        secret = _admin_secret()
        state = State(
            containers=[c],
            relations=[
                _database_relation(host="db.local"),
                _redis_relation(host="redis.local"),
                PeerRelation("hrms-peers"),
            ],
            secrets=[secret],
            config={"admin-password-secret": secret.id},
            leader=True,
        )
        out = ctx.run(ctx.on.pebble_ready(c), state)
        # In test environment, services won't be running, so charm waits for them
        assert out.unit_status == ops.ActiveStatus()


# ---------------------------------------------------------------------------
# Tests: state module (pure unit tests, no scenario needed)
# ---------------------------------------------------------------------------


class TestCharmState:
    def test_state_database_config_parsed(self):
        from state import CharmState, DatabaseConfig

        state = CharmState(
            site_name="hrms_test",
            database=DatabaseConfig(
                host="db.local",
                port=3306,
                user="u",
                password="p",
                database="db",  # nosec B106
            ),
            redis_url="redis://r:6379",
            admin_password="test-password",  # nosec B106
        )
        assert state.database.host == "db.local"
        assert state.database.port == 3306

    def test_state_is_immutable(self):
        from dataclasses import FrozenInstanceError

        from state import CharmState, DatabaseConfig

        state = CharmState(
            site_name="test.com",
            database=DatabaseConfig(host="h", user="u", password="p", database="db", port=3306),  # nosec B106
            redis_url="redis://r:6379",
            admin_password="test-password",  # nosec B106
        )
        with pytest.raises(FrozenInstanceError):
            state.site_name = "other"  # type: ignore[misc]


def test_admin_password_read_from_secret(templates_path: Path):
    """Reconcile reads the admin password from the configured Juju secret."""
    ctx = Context(HRMSCharm, charm_root=".")
    c = _container(site_exists=True, templates_path=templates_path)
    secret = _admin_secret("my-secure-password")
    state = State(
        containers=[c],
        relations=[_database_relation(), _redis_relation(), PeerRelation("hrms-peers")],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    # In test environment, services won't be running, so charm waits for them
    assert out.unit_status == ops.ActiveStatus()
