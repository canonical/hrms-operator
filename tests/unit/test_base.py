# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS charm."""

import json

import ops
import ops.testing
import pytest

from charm import HRMSCharm

CONTAINER = "frappe-hrms"
SITE_NAME = "hrms.example.com"
BENCH = "/home/frappe/frappe-bench"

_OK = ops.testing.ExecResult(exit_code=0)
_NO_SITE = ops.testing.ExecResult(exit_code=1)

# Nginx template content baked into the rock (minimal for tests)
_NGINX_TEMPLATE = (
    "server { server_name FRAPPE_SERVER_NAME; "
    "proxy_read_timeout PROXY_READ_TIMEOUT; "
    "client_max_body_size CLIENT_MAX_BODY_SIZE; "
    "add_header X-Frappe-Site FRAPPE_SITE_NAME_HEADER; }"
)


def make_harness(
    *,
    site_name: str = SITE_NAME,
    site_exists: bool = False,
) -> ops.testing.Harness:
    """Create and configure a Harness instance with exec handlers registered."""
    harness = ops.testing.Harness(HRMSCharm)
    harness.update_config(
        {
            "site-name": site_name,
        }
    )

    # setup_assets: chown and assets symlink
    harness.handle_exec(CONTAINER, ["chown"], result=_OK)
    harness.handle_exec(CONTAINER, ["bash", "-c"], result=_OK)

    # site sentinel check
    harness.handle_exec(
        CONTAINER,
        ["test", "-f"],
        result=_OK if site_exists else _NO_SITE,
    )

    # bench new-site
    harness.handle_exec(
        CONTAINER,
        [f"{BENCH}/env/bin/bench", "new-site"],
        result=ops.testing.ExecResult(exit_code=0, stdout="Site created"),
    )
    # bench --site <site> install-app / migrate / add-user
    harness.handle_exec(
        CONTAINER,
        [f"{BENCH}/env/bin/bench", "--site"],
        result=ops.testing.ExecResult(exit_code=0, stdout="Done"),
    )
    # rm -rf (old site dir)
    harness.handle_exec(CONTAINER, ["rm"], result=_OK)

    return harness


def _populate_nginx_template(harness: ops.testing.Harness) -> None:
    """Write the nginx template into the container filesystem for tests."""
    root = harness.get_filesystem_root(CONTAINER)
    nginx_dir = root / "templates" / "nginx"
    nginx_dir.mkdir(parents=True, exist_ok=True)
    (nginx_dir / "frappe.conf.template").write_text(_NGINX_TEMPLATE)


def add_mysql_relation(
    harness: ops.testing.Harness,
    host: str = "mariadb-host",
    port: int = 3306,
    user: str = "frappe_user",
    password: str = "db-password",
    database: str = "hrms_db",
) -> int:
    """Add a mysql relation with provider app data."""
    rel_id = harness.add_relation("mysql", "mariadb-k8s")
    harness.add_relation_unit(rel_id, "mariadb-k8s/0")
    harness.update_relation_data(
        rel_id,
        "mariadb-k8s",
        {
            "endpoints": f"{host}:{port}",
            "username": user,
            "password": password,
            "database": database,
        },
    )
    return rel_id


def add_redis_relation(
    harness: ops.testing.Harness,
    host: str = "redis-host",
    port: int = 6379,
) -> int:
    """Add a redis relation with unit data."""
    rel_id = harness.add_relation("redis", "redis-k8s")
    harness.add_relation_unit(rel_id, "redis-k8s/0")
    # RedisRequires reads hostname/port from the unit databag
    harness.update_relation_data(
        rel_id,
        "redis-k8s/0",
        {"hostname": host, "port": str(port)},
    )
    return rel_id


def add_ingress_relation(
    harness: ops.testing.Harness,
    url: str = "http://hrms.example.com",
) -> int:
    """Add an ingress relation with provider app data."""
    rel_id = harness.add_relation("ingress", "traefik-k8s")
    harness.add_relation_unit(rel_id, "traefik-k8s/0")
    # IngressPerAppRequirer reads from the provider app databag.
    harness.update_relation_data(
        rel_id,
        "traefik-k8s",
        {"ingress": json.dumps({"url": url})},
    )
    return rel_id


# ---------------------------------------------------------------------------
# Tests: initial blocking / waiting statuses
# ---------------------------------------------------------------------------


class TestBlockedStatus:
    def test_blocked_without_site_name(self):
        harness = ops.testing.Harness(HRMSCharm)
        harness.update_config({"site-name": ""})
        harness.begin()
        harness.charm.on.config_changed.emit()
        assert isinstance(harness.model.unit.status, ops.BlockedStatus)
        assert "site-name" in harness.model.unit.status.message

    def test_waiting_for_pebble_when_config_ok(self):
        harness = make_harness()
        harness.begin()
        harness.charm.on.config_changed.emit()
        assert isinstance(harness.model.unit.status, ops.WaitingStatus)

    def test_blocked_waiting_for_mysql(self):
        harness = make_harness()
        harness.begin()
        harness.set_can_connect(CONTAINER, True)
        harness.charm.on.config_changed.emit()
        assert isinstance(harness.model.unit.status, ops.BlockedStatus)
        assert "mysql" in harness.model.unit.status.message.lower()

    def test_blocked_waiting_for_redis(self):
        harness = make_harness()
        harness.begin()
        harness.set_can_connect(CONTAINER, True)
        add_mysql_relation(harness)
        harness.charm.on.config_changed.emit()
        assert isinstance(harness.model.unit.status, ops.BlockedStatus)
        assert "redis" in harness.model.unit.status.message.lower()

    def test_active_after_site_creation(self):
        """Reconcile creates the site when it doesn't exist and ends up Active."""
        harness = make_harness(site_exists=False)
        harness.begin()
        harness.add_relation("hrms-peers", "frappe-hrms")
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)
        assert isinstance(harness.model.unit.status, ops.ActiveStatus)

    def test_active_when_site_exists(self):
        harness = make_harness(site_exists=True)
        harness.begin()
        harness.add_relation("hrms-peers", "frappe-hrms")
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)
        assert isinstance(harness.model.unit.status, ops.ActiveStatus)


# ---------------------------------------------------------------------------
# Tests: pebble layer
# ---------------------------------------------------------------------------


class TestPebbleLayer:
    def _setup_ready_harness(self, **kwargs) -> ops.testing.Harness:
        harness = make_harness(**kwargs)
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        return harness

    def test_pebble_layer_has_all_services(self):
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        for svc in ("backend", "websocket", "frontend", "queue-short", "queue-long", "scheduler"):
            assert svc in plan.services, f"Service {svc!r} missing from pebble plan"

    def test_pebble_layer_services_all_enabled(self):
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        for name in ("backend", "websocket", "frontend", "queue-short", "queue-long", "scheduler"):
            assert plan.services[name].startup in (
                "enabled",
                ops.pebble.ServiceStartup.ENABLED,
            ), f"Service {name!r} should have startup=enabled"

    def test_pebble_checks_no_alive_level(self):
        """level=alive is prohibited by the charm guidelines."""
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        for check_name, check in plan.checks.items():
            assert check.level != ops.pebble.CheckLevel.ALIVE, (
                f"Check {check_name!r} must not use level=alive (prohibited by guidelines)"
            )

    def test_pebble_backend_uses_gunicorn(self):
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        assert "gunicorn" in plan.services["backend"].command

    def test_pebble_websocket_uses_node(self):
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        assert "node" in plan.services["websocket"].command

    def test_pebble_frontend_uses_nginx(self):
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        assert "nginx" in plan.services["frontend"].command

    def test_backend_check_failure_restarts_service(self):
        harness = self._setup_ready_harness()
        harness.container_pebble_ready(CONTAINER)

        plan = harness.get_container_pebble_plan(CONTAINER)
        on_failure = plan.services["backend"].on_check_failure
        assert "backend-up" in on_failure
        assert on_failure["backend-up"] == "restart"


# ---------------------------------------------------------------------------
# Tests: config file generation
# ---------------------------------------------------------------------------


class TestConfigFiles:
    def test_common_site_config_written(self):
        harness = make_harness()
        harness.begin()
        add_mysql_relation(harness, host="db.local", port=3306)
        add_redis_relation(harness, host="redis.local", port=6379)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)

        root = harness.get_filesystem_root(CONTAINER)
        config_path = root / "home/frappe/frappe-bench/sites/common_site_config.json"

        assert config_path.exists(), "common_site_config.json should be written"
        config = json.loads(config_path.read_text())

        assert config["db_host"] == "db.local"
        assert config["db_port"] == 3306
        assert config["redis_cache"] == "redis://redis.local:6379"
        assert config["redis_queue"] == "redis://redis.local:6379"
        assert config["socketio_port"] == 9000

    def test_nginx_config_written(self):
        harness = make_harness(site_name=SITE_NAME)
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)

        root = harness.get_filesystem_root(CONTAINER)
        nginx_path = root / "etc/nginx/conf.d/frappe.conf"

        assert nginx_path.exists(), "nginx frappe.conf should be written"
        content = nginx_path.read_text()
        assert SITE_NAME in content

    def test_nginx_uses_ingress_host_when_available(self):
        harness = make_harness(site_name=SITE_NAME)
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness)
        add_ingress_relation(harness, url="http://external.example.com")
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)

        root = harness.get_filesystem_root(CONTAINER)
        nginx_path = root / "etc/nginx/conf.d/frappe.conf"
        content = nginx_path.read_text()

        assert "external.example.com" in content

    def test_common_config_not_rewritten_when_unchanged(self):
        """configure() should return False when nothing changed."""
        from state import CharmState
        from workload import FrappeWorkload

        harness = make_harness(site_name=SITE_NAME)
        harness.begin()
        add_mysql_relation(harness, host="db.local")
        add_redis_relation(harness, host="redis.local")
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)

        charm = harness.charm
        state = CharmState.from_charm(charm, charm._database, charm._redis, charm._ingress)
        workload = FrappeWorkload(charm._container)

        # Second call should detect no change
        changed = workload.configure(state)
        assert changed is False


# ---------------------------------------------------------------------------
# Tests: state module
# ---------------------------------------------------------------------------


class TestCharmState:
    def test_state_raises_on_missing_site_name(self):
        from state import CharmState, InvalidConfigError

        harness = ops.testing.Harness(HRMSCharm)
        harness.update_config({"site-name": ""})
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness)

        with pytest.raises(InvalidConfigError) as exc_info:
            CharmState.from_charm(
                harness.charm,
                harness.charm._database,
                harness.charm._redis,
                harness.charm._ingress,
            )
        assert exc_info.value.key == "site-name"

    def test_state_database_config_parsed(self):
        from state import CharmState

        harness = make_harness()
        harness.begin()
        add_mysql_relation(harness, host="db.local", port=3306, user="frappe_user", password="pw")
        add_redis_relation(harness)

        state = CharmState.from_charm(
            harness.charm,
            harness.charm._database,
            harness.charm._redis,
            harness.charm._ingress,
        )

        assert state.database is not None
        assert state.database.host == "db.local"
        assert state.database.port == 3306
        assert state.database.user == "frappe_user"
        assert state.database.password == "pw"

    def test_state_redis_config_parsed(self):
        from state import CharmState

        harness = make_harness()
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness, host="redis.local", port=6379)

        state = CharmState.from_charm(
            harness.charm,
            harness.charm._database,
            harness.charm._redis,
            harness.charm._ingress,
        )

        assert state.redis is not None
        assert state.redis.host == "redis.local"
        assert state.redis.port == 6379
        assert state.redis.url == "redis://redis.local:6379"

    def test_state_no_external_host_without_ingress(self):
        from state import CharmState

        harness = make_harness()
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness)

        state = CharmState.from_charm(
            harness.charm,
            harness.charm._database,
            harness.charm._redis,
            harness.charm._ingress,
        )
        assert state.external_host is None

    def test_state_external_host_from_ingress(self):
        from state import CharmState

        harness = make_harness()
        harness.begin()
        add_mysql_relation(harness)
        add_redis_relation(harness)
        add_ingress_relation(harness, url="http://external.example.com/hrms")

        state = CharmState.from_charm(
            harness.charm,
            harness.charm._database,
            harness.charm._redis,
            harness.charm._ingress,
        )
        assert state.external_host == "external.example.com"

    def test_redis_config_url_property(self):
        from state import RedisConfig

        redis = RedisConfig(host="localhost", port=6379)
        assert redis.url == "redis://localhost:6379"

    def test_state_is_immutable(self):
        import pydantic

        from state import CharmState, DatabaseConfig, RedisConfig

        state = CharmState(
            site_name="test.com",
            database=DatabaseConfig(host="h", user="u", password="p", database="db"),
            redis=RedisConfig(host="r"),
        )
        with pytest.raises(pydantic.ValidationError):
            state.site_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: actions
# ---------------------------------------------------------------------------


class TestActions:
    def _setup_active_harness(self) -> ops.testing.Harness:
        """Return a harness with site created and charm active."""
        harness = make_harness(site_exists=True)
        harness.begin()
        peer_id = harness.add_relation("hrms-peers", "frappe-hrms")
        harness.update_relation_data(peer_id, "frappe-hrms", {"admin-password": "stored-pw-123"})
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)
        return harness

    def test_get_admin_credentials(self):
        harness = self._setup_active_harness()
        harness.run_action("get-admin-credentials")

    def test_get_admin_credentials_fails_without_password(self):
        harness = make_harness(site_exists=True)
        harness.begin()
        harness.add_relation("hrms-peers", "frappe-hrms")
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)

        with pytest.raises(ops.testing.ActionFailed):
            harness.run_action("get-admin-credentials")

    def test_create_user(self):
        harness = self._setup_active_harness()
        harness.run_action(
            "create-user",
            {"email": "user@example.com", "first-name": "Test"},
        )

    def test_create_user_fails_without_site(self):
        harness = make_harness(site_exists=False)
        harness.begin()
        harness.add_relation("hrms-peers", "frappe-hrms")
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)

        with pytest.raises(ops.testing.ActionFailed):
            harness.run_action(
                "create-user",
                {"email": "user@example.com", "first-name": "Test"},
            )

    def test_admin_password_auto_generated_on_site_creation(self):
        """When site doesn't exist, reconcile generates and stores admin password."""
        harness = make_harness(site_exists=False)
        harness.set_leader(True)
        harness.begin()
        peer_id = harness.add_relation("hrms-peers", "frappe-hrms")
        add_mysql_relation(harness)
        add_redis_relation(harness)
        _populate_nginx_template(harness)
        harness.set_can_connect(CONTAINER, True)
        harness.container_pebble_ready(CONTAINER)

        assert isinstance(harness.model.unit.status, ops.ActiveStatus)
        peer_data = harness.get_relation_data(peer_id, "frappe-hrms")
        assert "admin-password" in peer_data
        assert len(peer_data["admin-password"]) == 24
