# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS workload helpers."""

from unittest.mock import Mock

import ops
import pytest
from scenario import Context, PeerRelation, State

from charm import HRMSCharm
from unit.conftest import (
    CONTAINER,
    make_admin_secret,
    make_container,
    make_database_relation,
    make_redis_relation,
)
from workload import SITE_NAME, FrappeWorkload, WorkloadError


def test_truncate_output_tail():
    assert FrappeWorkload._truncate_output_tail(None) is None
    assert FrappeWorkload._truncate_output_tail("short", max_chars=100) == "short"
    assert FrappeWorkload._truncate_output_tail("a" * 20, max_chars=5) == "aaaaa"


def test_pebble_layer_includes_statsd_exporter():
    workload = FrappeWorkload(Mock())
    layer = workload._build_pebble_layer()

    assert "statsd-exporter" in layer["services"]
    statsd = layer["services"]["statsd-exporter"]
    assert "/bin/statsd_exporter" in statsd["command"]
    assert "--statsd.listen-udp=localhost:9125" in statsd["command"]
    assert "--web.listen-address=:9102" in statsd["command"]

    backend_command = layer["services"]["backend"]["command"]
    assert "--statsd-host=localhost:9125" in backend_command
    assert "--statsd-prefix=frappe_hrms" in backend_command


def test_statsd_exporter_is_a_reconciled_service():
    from workload import SERVICES

    assert "statsd-exporter" in SERVICES


def test_services_healthy_false_when_not_started():
    ctx = Context(HRMSCharm, charm_root=".")
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
    with ctx(ctx.on.pebble_ready(c), state) as manager:
        workload = FrappeWorkload(manager.charm.unit.get_container(CONTAINER))
        # No layer/services exist yet, so no service reports a healthy status.
        assert workload.services_healthy() is False


def test_get_installed_apps_returns_empty_when_site_missing():
    container = Mock()
    proc = Mock()
    proc.wait_output.side_effect = ops.pebble.ExecError(
        ["bench", "--site", SITE_NAME, "list-apps"],
        2,
        "",
        f"Error: 404 Not Found: {SITE_NAME} does not exist.\n",
    )
    container.exec.return_value = proc

    workload = FrappeWorkload(container)

    assert workload._get_installed_apps(SITE_NAME) == []


def test_get_installed_apps_raises_on_unexpected_failure():
    container = Mock()
    proc = Mock()
    proc.wait_output.side_effect = ops.pebble.ExecError(
        ["bench", "--site", SITE_NAME, "list-apps"],
        2,
        "",
        "unexpected failure",
    )
    container.exec.return_value = proc

    workload = FrappeWorkload(container)

    with pytest.raises(WorkloadError):
        workload._get_installed_apps(SITE_NAME)
