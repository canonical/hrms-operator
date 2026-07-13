# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS workload helpers."""

from scenario import Context, PeerRelation, State

from charm import HRMSCharm
from unit.conftest import (
    CONTAINER,
    make_admin_secret,
    make_container,
    make_database_relation,
    make_redis_relation,
)
from workload import FrappeWorkload


def test_truncate_output_tail():
    assert FrappeWorkload._truncate_output_tail(None) is None
    assert FrappeWorkload._truncate_output_tail("short", max_chars=100) == "short"
    assert FrappeWorkload._truncate_output_tail("a" * 20, max_chars=5) == "aaaaa"


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
