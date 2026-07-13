# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS config file generation."""

import json
from pathlib import Path
from unittest import mock

import ops
from scenario import Container, Context, Mount, PeerRelation, State

from charm import HRMSCharm
from unit.conftest import (
    CONTAINER,
    make_admin_secret,
    make_container,
    make_database_relation,
    make_execs,
    make_redis_relation,
)
from workload import COMMON_SITE_CONFIG, SITES_DIR


def test_common_site_config_written():
    ctx = Context(HRMSCharm, charm_root=".")
    c = make_container(site_exists=True)
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(host="db.local", port=3306),
            make_redis_relation(host="redis.local", port=6379),
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


def test_common_config_not_rewritten_when_unchanged(tmp_path: Path):
    """A second reconcile with identical state does not push common_site_config.json again."""
    # Back the sites dir with a real tmp dir so the written config persists
    # across the two reconcile runs below.
    sites_source = tmp_path / "sites"
    sites_source.mkdir()
    ctx = Context(HRMSCharm, charm_root=".")
    c = Container(
        CONTAINER,
        can_connect=True,
        execs=make_execs(site_exists=True),
        mounts={
            "sites": Mount(location=SITES_DIR, source=sites_source),
        },
    )
    secret = make_admin_secret()
    state = State(
        containers=[c],
        relations=[
            make_database_relation(host="db.local"),
            make_redis_relation(host="redis.local"),
            PeerRelation("hrms-peers"),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
        leader=True,
    )

    # autospec forwards ``self``; side_effect calls the real push so the file is
    # actually written and the second reconcile sees identical content.
    with mock.patch.object(
        ops.Container, "push", autospec=True, side_effect=ops.Container.push
    ) as push:
        out = ctx.run(ctx.on.pebble_ready(c), state)
        pushed = [call.args[1] for call in push.call_args_list]
        assert COMMON_SITE_CONFIG in pushed, "config should be pushed on first reconcile"

        # Re-run against the resulting state; the file content is now identical.
        push.reset_mock()
        ctx.run(ctx.on.pebble_ready(out.get_container(CONTAINER)), out)
        pushed = [call.args[1] for call in push.call_args_list]
        assert COMMON_SITE_CONFIG not in pushed, "unchanged config must not be pushed again"
