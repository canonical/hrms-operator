# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm runtime state abstraction."""

import logging
from urllib.parse import urlparse

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.redis_k8s.v0.redis import RedisRequires
from pydantic import Field, SecretStr
from pydantic.dataclasses import dataclass

logger = logging.getLogger(__name__)


class MissingConfigError(Exception):
    """Missing charm configuration."""


class InvalidConfigError(Exception):
    """Invalid content in charm configurations."""


class MissingIntegrationError(Exception):
    """Missing charm integration."""


class InvalidIntegrationError(Exception):
    """Invalid content in integrations."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Database connection configuration."""

    password: SecretStr
    host: str = Field(min_length=1)
    user: str = Field(min_length=1)
    database: str = Field(min_length=1)
    port: int = Field(gt=0)


@dataclass(frozen=True)
class CharmState:
    """State of the Frappe HRMS charm."""

    database: DatabaseConfig
    admin_password: SecretStr
    redis_url: str = Field(min_length=1)

    @classmethod
    def from_charm(
        cls,
        charm: ops.CharmBase,
        database_requirer: DatabaseRequires,
        redis_requirer: RedisRequires,
    ) -> "CharmState":
        """Build CharmState from the charm object and its integrations.

        Raises:
            MissingIntegrationError: When a required integration is not ready.
            InvalidIntegrationError: When a required integration has published
                malformed data.
            MissingConfigError: When required configuration is unset.
            InvalidConfigError: When configuration content is invalid.
        """
        database = cls._fetch_database_details(database_requirer)
        redis_url = cls._fetch_redis_url(redis_requirer)
        admin_password = cls._fetch_admin_password(charm)

        return cls(
            database=database,
            redis_url=redis_url,
            admin_password=admin_password,
        )

    @staticmethod
    def _fetch_admin_password(charm: ops.CharmBase) -> SecretStr:
        """Read the admin password from the configured Juju secret.

        Raises:
            MissingConfigError: When the admin-password-secret config is unset.
            InvalidConfigError: When the secret is unreadable or the 'password'
                value is missing.
        """
        admin_password_secret_id = (
            str(charm.config.get("admin-password-secret", "")).strip() or None
        )
        if not admin_password_secret_id:
            raise MissingConfigError("Configuration 'admin-password-secret' must be set ")
        try:
            content = charm.model.get_secret(id=admin_password_secret_id).get_content()
            admin_password = content.get("password", "")
        except ops.SecretNotFoundError as e:
            raise InvalidConfigError(
                "Configuration 'admin-password-secret' refers to a secret that does not exist"
            ) from e
        except ops.ModelError as e:
            raise InvalidConfigError(
                "Configuration 'admin-password-secret' could not be read; the charm may not "
                "have permission to access the secret"
            ) from e
        if not admin_password:
            raise InvalidConfigError(
                "Configuration 'admin-password-secret' must contain a non-empty 'password' value"
            )
        return SecretStr(admin_password)

    @staticmethod
    def _fetch_database_details(
        database_requirer: DatabaseRequires,
    ) -> DatabaseConfig:
        """Extract database config from the DatabaseRequires helper.

        Raises:
            MissingIntegrationError: When the integration is not ready yet.
            InvalidIntegrationError: When the relation has published data but it
                is malformed.
        """
        relation_data = database_requirer.fetch_relation_data()
        if not relation_data:
            raise MissingIntegrationError("Integration 'database' is required but not ready")

        # 'database' is declared with limit: 1, so there is at most one relation.
        data = next(iter(relation_data.values()))

        endpoints = data.get("endpoints", "")
        if not endpoints:
            raise MissingIntegrationError("Integration 'database' is required but not ready")

        # endpoints may be "host:port" or "host:port,replica:port"
        primary_endpoint = endpoints.split(",")[0].strip()
        parts = primary_endpoint.split(":")
        if len(parts) != 2:
            raise InvalidIntegrationError(
                f"Integration 'database' endpoint is not in 'host:port' form: {endpoints}"
            )
        host, port_str = parts

        return DatabaseConfig(
            host=host,
            port=port_str,
            user=data.get("username"),
            password=data.get("password"),
            database=data.get("database"),
        )

    @staticmethod
    def _fetch_redis_url(
        redis_requirer: RedisRequires,
    ) -> str:
        """Extract a Redis URL from the RedisRequires helper.

        Raises:
            MissingIntegrationError: Until the remote unit has published a URL
                with both hostname and port.
            InvalidIntegrationError: When the published URL is malformed (e.g. a
                non-numeric port).
        """
        url = redis_requirer.url
        if not url:
            raise MissingIntegrationError("Integration 'redis' is required but not ready")

        parsed = urlparse(url)

        try:
            port = parsed.port
        except ValueError as exc:
            raise InvalidIntegrationError(
                f"Integration 'redis' published a malformed URL: {url}"
            ) from exc

        if not parsed.hostname or port is None:
            logger.info("Redis URL not yet complete: %s", url)
            raise MissingIntegrationError("Integration 'redis' is required but not ready")

        return f"redis://{parsed.hostname}:{port}"
