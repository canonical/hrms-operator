# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm runtime state abstraction.

This module abstracts all charm runtime state, providing a clean interface
between Juju's data model and the charm/workload logic. All Juju-level state
access (config, relation data, etc.) is contained here.

See: https://discourse.charmhub.io/t/specification-isd014-managing-charm-complexity/11619
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

import ops
import pydantic

if TYPE_CHECKING:
    from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
    from charms.redis_k8s.v0.redis import RedisRequires
    from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

logger = logging.getLogger(__name__)


class InvalidConfigError(Exception):
    """Raised when the charm configuration is invalid or incomplete."""

    def __init__(self, key: str, reason: str = "is required") -> None:
        """Initialise with the config key and reason."""
        self.key = key
        super().__init__(f"Configuration '{key}' {reason}")


class MissingRelationError(Exception):
    """Raised when a required integration is missing or not yet ready."""

    def __init__(self, relation_name: str) -> None:
        """Initialise with the relation name."""
        self.relation_name = relation_name
        super().__init__(f"Integration '{relation_name}' is required but not ready")


class DatabaseConfig(pydantic.BaseModel):
    """Database connection configuration."""

    host: str
    port: int = 3306
    user: str
    password: str
    database: str

    model_config = pydantic.ConfigDict(frozen=True)


class RedisConfig(pydantic.BaseModel):
    """Redis connection configuration."""

    host: str
    port: int = 6379

    model_config = pydantic.ConfigDict(frozen=True)

    @property
    def url(self) -> str:
        """Return the Redis connection URL."""
        return f"redis://{self.host}:{self.port}"


class CharmState(pydantic.BaseModel):
    """Complete runtime state of the Frappe HRMS charm.

    Populated via :meth:`from_charm`. All access to Juju-level state
    (config, relations, etc.) is encapsulated in this class and in
    ``from_charm``. Downstream code (workload, tests) only interacts with
    instances of this model.
    """

    # Frappe site configuration
    site_name: str
    admin_password: str

    # Integration data (None if not yet available)
    database: Optional[DatabaseConfig] = None
    redis: Optional[RedisConfig] = None

    # Ingress: external hostname provided by Traefik (None if no ingress)
    external_host: Optional[str] = None

    model_config = pydantic.ConfigDict(frozen=True)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_charm(
        cls,
        charm: ops.CharmBase,
        database_requirer: DatabaseRequires,
        redis_requirer: RedisRequires,
        ingress_requirer: IngressPerAppRequirer,
    ) -> CharmState:
        """Build CharmState from the live charm object and its integration helpers.

        Raises:
            InvalidConfigError: When a required config option is missing.
            MissingRelationError: When a required integration is not ready.
        """
        site_name = str(charm.config.get("site-name", "")).strip()
        if not site_name:
            raise InvalidConfigError("site-name")

        admin_password = str(charm.config.get("admin-password", "")).strip()
        if not admin_password:
            raise InvalidConfigError("admin-password")

        database = cls._collect_database(database_requirer, site_name)
        redis = cls._collect_redis(redis_requirer)
        external_host = cls._collect_ingress_host(ingress_requirer)

        return cls(
            site_name=site_name,
            admin_password=admin_password,
            database=database,
            redis=redis,
            external_host=external_host,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_database(
        database_requirer: DatabaseRequires,
        site_name: str,
    ) -> Optional[DatabaseConfig]:
        """Extract database config from the DatabaseRequires helper."""
        if not database_requirer.is_resource_created():
            return None

        relation_data = database_requirer.fetch_relation_data()
        for data in relation_data.values():
            endpoints = data.get("endpoints", "")
            if not endpoints:
                continue

            # endpoints may be "host:port" or "host:port,replica:port"
            primary_endpoint = endpoints.split(",")[0].strip()
            if ":" in primary_endpoint:
                host, port_str = primary_endpoint.rsplit(":", 1)
                port = int(port_str)
            else:
                host = primary_endpoint
                port = 3306

            # Derive db name from site name (mariadb-k8s sets database == username).
            db_name = data.get("database", "") or re.sub(r"[.\-]", "_", site_name)

            # Use the username from the relation data (mariadb-k8s creates a
            # user with the same name as the database, which Frappe requires).
            db_user = data.get("username", "") or db_name

            return DatabaseConfig(
                host=host,
                port=port,
                user=db_user,
                password=data.get("password", ""),
                database=db_name,
            )

        return None

    @staticmethod
    def _collect_redis(
        redis_requirer: RedisRequires,
    ) -> Optional[RedisConfig]:
        """Extract Redis config from the RedisRequires helper."""
        url = redis_requirer.url
        if not url:
            return None

        parsed = urlparse(url)
        if not parsed.hostname:
            logger.warning("Could not parse Redis URL: %s", url)
            return None

        return RedisConfig(host=parsed.hostname, port=parsed.port or 6379)

    @staticmethod
    def _collect_ingress_host(
        ingress_requirer: IngressPerAppRequirer,
    ) -> Optional[str]:
        """Extract the external hostname provided by the ingress integration."""
        ingress_url = ingress_requirer.url
        if not ingress_url:
            return None

        parsed = urlparse(ingress_url)
        return parsed.hostname or None
