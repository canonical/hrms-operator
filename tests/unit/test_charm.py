# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS charm."""

from unittest import mock

import ops
import pytest
from pydantic import ValidationError
from scenario import Container, Context, Exec, PeerRelation, State
from scenario.errors import UncaughtCharmError

from charm import HRMSCharm
from state import CharmState
from unit.conftest import (
    BENCH,
    CONTAINER,
    DRIFTED_DISK_VERSIONS,
    make_admin_secret,
    make_container,
    make_database_relation,
    make_execs,
    make_valkey_relation,
    make_valkey_response,
)
from workload import WorkloadError


def test_waiting_for_pebble():
    ctx = Context(HRMSCharm, charm_root=".")
    container = Container(CONTAINER, can_connect=False)
    state = State(containers=[container])
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == ops.WaitingStatus("Waiting for Pebble to be ready")


def test_blocked_waiting_for_database():
    ctx = Context(HRMSCharm, charm_root=".")
    c = Container(CONTAINER, can_connect=True, execs=make_execs())
    state = State(containers=[c])
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(out.unit_status, ops.BlockedStatus)
    assert "check the debug logs" in out.unit_status.message.lower()


def test_blocked_waiting_for_valkey():
    ctx = Context(HRMSCharm, charm_root=".")
    c = Container(CONTAINER, can_connect=True, execs=make_execs())
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[make_database_relation(), make_valkey_relation(), PeerRelation("hrms-peers")],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    with mock.patch.object(CharmState, "_fetch_valkey_responses", return_value=[]):
        out = ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(out.unit_status, ops.BlockedStatus)
    assert "check the debug logs" in out.unit_status.message.lower()


def test_block_when_valkey_not_reachable_for_site_init():
    """When the Valkey response has no port yet, reconcile should block."""
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=False)
    secret = make_admin_secret()
    incomplete = make_valkey_response(endpoints="valkey-host")
    state = State(
        containers=[c],
        relations=[make_database_relation(), make_valkey_relation(), PeerRelation("hrms-peers")],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    with mock.patch.object(CharmState, "_fetch_valkey_responses", return_value=[incomplete]):
        out = ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(out.unit_status, ops.BlockedStatus)
    assert "check the debug logs" in out.unit_status.message.lower()


def test_existing_site_installs_missing_hrms_app():
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(
        site_exists=True,
        installed_apps_output="frappe 16.0.0 version-16\nerpnext 16.0.0 version-16\n",
    )
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.ActiveStatus()
    install_commands = [
        args.command for args in ctx.exec_history[CONTAINER] if "install-app" in args.command
    ]
    assert install_commands == [
        [f"{BENCH}/env/bin/bench", "--site", "frappe-hrms", "install-app", "hrms"]
    ]


def test_creates_new_site_when_apps_missing():
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=False, installed_apps_output="")
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.ActiveStatus()
    commands = [args.command for args in ctx.exec_history[CONTAINER]]
    assert any("new-site" in cmd for cmd in commands), "a new site should be created"
    install_commands = [cmd for cmd in commands if "install-app" in cmd]
    assert [
        f"{BENCH}/env/bin/bench",
        "--site",
        "frappe-hrms",
        "install-app",
        "erpnext",
    ] in install_commands
    assert [
        f"{BENCH}/env/bin/bench",
        "--site",
        "frappe-hrms",
        "install-app",
        "hrms",
    ] in install_commands


def test_workload_error_raises():
    ctx = Context(HRMSCharm, charm_root=".")
    # chown fails during setup_assets, so the workload raises WorkloadError.
    c = Container(CONTAINER, can_connect=True, execs={Exec(["chown"], return_code=1)})
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    with pytest.raises(UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(exc_info.value.__cause__, WorkloadError)


def test_new_site_failure_raises():
    ctx = Context(HRMSCharm, charm_root=".")
    # No site exists, no apps installed, and bench new-site fails.
    c = Container(
        CONTAINER,
        can_connect=True,
        execs={
            Exec(["chown"], return_code=0),
            Exec(["test", "-f"], return_code=1),
            Exec([f"{BENCH}/env/bin/bench", "--site"], return_code=0, stdout=""),
            Exec([f"{BENCH}/env/bin/bench", "new-site"], return_code=1),
        },
    )
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    with pytest.raises(UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(exc_info.value.__cause__, WorkloadError)


def test_install_app_failure_raises():
    ctx = Context(HRMSCharm, charm_root=".")
    # list-apps/install-app both fail: list-apps errors are swallowed (empty
    # apps) but the subsequent install-app failure raises WorkloadError.
    c = Container(
        CONTAINER,
        can_connect=True,
        execs={
            Exec(["chown"], return_code=0),
            Exec(["test", "-f"], return_code=1),
            Exec([f"{BENCH}/env/bin/bench", "new-site"], return_code=0),
            Exec([f"{BENCH}/env/bin/bench", "--site"], return_code=1),
        },
    )
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    with pytest.raises(UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(exc_info.value.__cause__, WorkloadError)


def test_installs_only_missing_apps():
    ctx = Context(HRMSCharm, charm_root=".")
    # hrms already present but erpnext missing: only erpnext is installed.
    c = make_container(
        site_exists=True,
        installed_apps_output="frappe 16.0.0 version-16\nhrms 16.0.0 version-16\n",
    )
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.ActiveStatus()
    install_commands = [
        args.command for args in ctx.exec_history[CONTAINER] if "install-app" in args.command
    ]
    assert [
        f"{BENCH}/env/bin/bench",
        "--site",
        "frappe-hrms",
        "install-app",
        "erpnext",
    ] in install_commands
    assert [
        f"{BENCH}/env/bin/bench",
        "--site",
        "frappe-hrms",
        "install-app",
        "hrms",
    ] not in install_commands


def test_waiting_when_services_not_healthy(monkeypatch):
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=True)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    monkeypatch.setattr("charm.FrappeWorkload.services_healthy", lambda self: False)
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.WaitingStatus("Waiting for services to become healthy")


def test_waiting_when_check_not_up():
    ctx = Context(HRMSCharm, charm_root=".")
    # Services run, but the frontend-ready check has not passed yet.
    c = make_container(site_exists=True, checks_healthy=False)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.WaitingStatus("Waiting for services to become healthy")


def test_blocked_when_no_admin_password_secret():
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=True)
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(out.unit_status, ops.BlockedStatus)
    assert "check the debug logs" in out.unit_status.message.lower()


def test_blocked_when_state_validation_fails(monkeypatch):
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=True)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
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


def test_active_when_site_exists():
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=True)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_valkey_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.ActiveStatus()


def test_metrics_endpoint_scrape_jobs_published():
    ctx = Context(HRMSCharm, charm_root=".")
    metrics = Relation("metrics-endpoint")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=True)],
        relations=[metrics],
    )
    out = ctx.run(ctx.on.relation_joined(metrics), state)
    data = out.get_relation(metrics.id).local_app_data
    assert "scrape_jobs" in data
    assert "9102" in data["scrape_jobs"]


def test_grafana_dashboard_relation_joins_without_error():
    ctx = Context(HRMSCharm, charm_root=".")
    grafana = Relation("grafana-dashboard")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=True)],
        relations=[grafana],
    )
    out = ctx.run(ctx.on.relation_joined(grafana), state)
    # The relation joins cleanly; the dashboards payload is populated in a later change.
    assert out.get_relation(grafana.id) is not None


def test_prometheus_alert_rules_published():
    ctx = Context(HRMSCharm, charm_root=".")
    metrics = Relation("metrics-endpoint")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=True)],
        relations=[metrics],
    )
    out = ctx.run(ctx.on.relation_joined(metrics), state)
    data = out.get_relation(metrics.id).local_app_data
    assert "alert_rules" in data
    # Built-in host-health alert injected by MetricsEndpointProvider.
    assert "HostDown" in data["alert_rules"]
    # Bundled application alert.
    assert "HRMSHighServerErrorRatio" in data["alert_rules"]


def test_grafana_dashboard_payload_is_non_empty():
    ctx = Context(HRMSCharm, charm_root=".")
    grafana = Relation("grafana-dashboard")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=True)],
        relations=[grafana],
    )
    out = ctx.run(ctx.on.relation_created(grafana), state)
    data = out.get_relation(grafana.id).local_app_data
    assert data["dashboards"]


def test_migration_runs_when_version_drift_detected():
    """Reconcile should run bench migrate when disk version differs from DB version."""
    ctx = Context(HRMSCharm, charm_root=".")
    # Simulate version drift: disk has 16.0.1, list-apps (DB) has 16.0.0
    c = make_container(site_exists=True, disk_versions=DRIFTED_DISK_VERSIONS)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_redis_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    # pebble_ready is emitted when charm upgrades (container restarts)
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.ActiveStatus()
    migrate_commands = [
        args.command for args in ctx.exec_history[CONTAINER] if "migrate" in args.command
    ]
    assert [
        f"{BENCH}/env/bin/bench",
        "--site",
        "frappe-hrms",
        "migrate",
    ] in migrate_commands


def test_migration_skipped_when_versions_match():
    """Reconcile should not run migrate when disk and DB versions match."""
    ctx = Context(HRMSCharm, charm_root=".")
    # Simulate matching versions: no migration needed
    c = make_container(site_exists=True)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_redis_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    out = ctx.run(ctx.on.pebble_ready(c), state)
    assert out.unit_status == ops.ActiveStatus()
    # Verify migrate was NOT called
    migrate_commands = [
        args.command for args in ctx.exec_history[CONTAINER] if "migrate" in args.command
    ]
    assert [
        f"{BENCH}/env/bin/bench",
        "--site",
        "frappe-hrms",
        "migrate",
    ] not in migrate_commands


def test_migration_errors_raises_workload_error():
    """Reconcile raises WorkloadError if bench migrate fails."""
    ctx = Context(HRMSCharm, charm_root=".")
    # Simulate version drift with migrate failure
    c = make_container(
        site_exists=True,
        disk_versions=DRIFTED_DISK_VERSIONS,
        migrate_return_code=1,
    )
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(),
            make_redis_relation(),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )
    with pytest.raises(UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.pebble_ready(c), state)
    assert isinstance(exc_info.value.__cause__, WorkloadError)
