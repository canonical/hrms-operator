# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm integration tests."""

from collections.abc import Generator

import jubilant
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Parse additional pytest options."""
    parser.addoption(
        "--model",
        action="store",
        default=None,
        help="Juju model name.",
    )
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="Keep temporarily-created models after tests.",
    )


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Provide a Juju instance, either for an existing model or a temporary one."""
    model = request.config.getoption("--model")
    if model:
        yield jubilant.Juju(model=model)
        return

    keep = request.config.getoption("--keep-models")
    with jubilant.temp_model(keep=keep) as j:
        yield j
