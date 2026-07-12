# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm integration tests."""

import json
import subprocess
import typing
from collections.abc import Generator

import jubilant
import pytest


@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Provide a Juju instance, either for an existing model or a temporary one."""

    def show_debug_log(juju: jubilant.Juju) -> None:
        if request.session.testsfailed:
            try:
                log = juju.debug_log(limit=1000)
                print(log, end="")
            except Exception as exc:  # pragma: nocover - best effort diagnostics
                print(f"Skipping debug-log capture: {exc}")

    def model_exists(model_name: str) -> bool:
        """Return True if the requested Juju model currently exists."""
        result = subprocess.run(
            ["juju", "models", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        models = json.loads(result.stdout).get("models", [])
        names = {m.get("name", "") for m in models}
        short_names = {m.get("short-name", "") for m in models}
        return model_name in names or model_name in short_names

    def ensure_model_exists(model_name: str) -> None:
        """Create the target model when tests run against an explicit --model."""
        if model_exists(model_name):
            return
        subprocess.run(["juju", "add-model", model_name], check=True, text=True)

    model = request.config.getoption("--model")
    if model:
        ensure_model_exists(model)
        juju = jubilant.Juju(model=model)
        yield juju
        show_debug_log(juju)
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as juju:
        yield juju
        show_debug_log(juju)
