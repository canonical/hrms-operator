# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Frappe HRMS charm state module."""

from unittest import mock

import ops
import pytest
from pydantic import ValidationError
from scenario import Container, Context, Relation, Secret, State

from charm import HRMSCharm
from state import (
    CharmState,
    InvalidConfigError,
    InvalidIntegrationError,
    MissingConfigError,
    MissingIntegrationError,
)
from unit.conftest import (
    CONTAINER,
    make_admin_secret,
    make_database_relation,
    make_valkey_relation,
    make_valkey_response,
)


def _load_charm_state(state: State) -> CharmState:
    """Run CharmState.from_charm against a live charm instance built from ``state``."""
    ctx = Context(HRMSCharm, charm_root=".")
    with ctx(ctx.on.update_status(), state) as manager:
        charm = manager.charm
        return CharmState.from_charm(charm, charm._database, charm._valkey)


def test_all_integrations_ready():
    secret = make_admin_secret("super-secret")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[
            make_database_relation(host="db.local", port=5432),
            make_valkey_relation(),
        ],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
    )

    with mock.patch.object(
        CharmState,
        "_fetch_valkey_responses",
        return_value=[make_valkey_response(host="valkey.local", port=6380)],
    ):
        result = _load_charm_state(state)

    assert result.database.host == "db.local"
    assert result.database.port == 5432
    assert result.database.user == "frappe_user"
    assert result.database.password.get_secret_value() == "db-password"
    assert result.database.database == "hrms_db"
    assert result.valkey_url == "redis://hrms:valkey-pass@valkey.local:6380"
    assert result.admin_password.get_secret_value() == "super-secret"


def test_missing_database_relation():
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
    )
    with pytest.raises(
        MissingIntegrationError, match="Integration 'database' is required but not ready"
    ):
        _load_charm_state(state)


def test_database_relation_without_endpoints():
    database = Relation(
        "database",
        remote_app_name="mariadb-k8s",
        remote_app_data={"username": "u", "password": "p", "database": "d"},
    )
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[database],
    )
    with pytest.raises(
        MissingIntegrationError, match="Integration 'database' is required but not ready"
    ):
        _load_charm_state(state)


def test_database_endpoint_not_host_port():
    database = Relation(
        "database",
        remote_app_name="mariadb-k8s",
        remote_app_data={
            "endpoints": "host-without-port",
            "username": "u",
            "password": "p",
            "database": "d",
        },
    )
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[database],
    )
    with pytest.raises(
        InvalidIntegrationError, match="Integration 'database' endpoint is not in 'host:port' form"
    ):
        _load_charm_state(state)


def test_database_non_numeric_port():
    database = Relation(
        "database",
        remote_app_name="mariadb-k8s",
        remote_app_data={
            "endpoints": "db.local:not-a-port",
            "username": "u",
            "password": "p",
            "database": "d",
        },
    )
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[database],
    )
    with pytest.raises(ValidationError):
        _load_charm_state(state)


def test_missing_valkey_relation():
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation()],
    )
    with (
        mock.patch.object(CharmState, "_fetch_valkey_responses", return_value=[]),
        pytest.raises(
            MissingIntegrationError, match="Integration 'valkey' is required but not ready"
        ),
    ):
        _load_charm_state(state)


def test_valkey_incomplete_without_port():
    response = make_valkey_response(endpoints="valkey-host")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
    )
    with (
        mock.patch.object(CharmState, "_fetch_valkey_responses", return_value=[response]),
        pytest.raises(
            MissingIntegrationError, match="Integration 'valkey' is required but not ready"
        ),
    ):
        _load_charm_state(state)


def test_valkey_malformed_port():
    response = make_valkey_response(endpoints="valkey-host:not-a-port")
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
    )
    with (
        mock.patch.object(CharmState, "_fetch_valkey_responses", return_value=[response]),
        pytest.raises(
            InvalidIntegrationError, match="Integration 'valkey' published a malformed endpoint"
        ),
    ):
        _load_charm_state(state)


def test_valkey_tls_unsupported():
    response = make_valkey_response(tls=True)
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
    )
    with (
        mock.patch.object(CharmState, "_fetch_valkey_responses", return_value=[response]),
        pytest.raises(InvalidIntegrationError, match="Integration 'valkey' has TLS enabled"),
    ):
        _load_charm_state(state)


def test_missing_admin_password_config():
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
    )
    with pytest.raises(
        MissingConfigError, match="Configuration 'admin-password-secret' must be set"
    ):
        _load_charm_state(state)


def test_admin_password_secret_not_found():
    orphan_secret = make_admin_secret()
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
        config={"admin-password-secret": orphan_secret.id},
    )
    with pytest.raises(
        InvalidConfigError,
        match="Configuration 'admin-password-secret' refers to a secret that does not exist",
    ):
        _load_charm_state(state)


def test_admin_password_secret_without_password_key():
    secret = Secret({"not-password": "value"})
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
    )
    with pytest.raises(
        InvalidConfigError,
        match="Configuration 'admin-password-secret' must contain a non-empty 'password' value",
    ):
        _load_charm_state(state)


def test_admin_password_secret_unreadable(monkeypatch):
    original_get_secret = ops.Model.get_secret

    def raise_on_id_lookup(self, *args, **kwargs):
        if kwargs.get("id") is not None:
            raise ops.ModelError("permission denied")
        return original_get_secret(self, *args, **kwargs)

    monkeypatch.setattr(ops.Model, "get_secret", raise_on_id_lookup)
    secret = make_admin_secret()
    state = State(
        leader=True,
        containers=[Container(CONTAINER, can_connect=False)],
        relations=[make_database_relation(), make_valkey_relation()],
        secrets=[secret],
        config={"admin-password-secret": secret.id},
    )
    with pytest.raises(
        InvalidConfigError, match="Configuration 'admin-password-secret' could not be read"
    ):
        _load_charm_state(state)
