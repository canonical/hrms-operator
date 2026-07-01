# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared pytest options for all test suites."""

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
