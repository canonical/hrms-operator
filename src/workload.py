# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS workload operations.

All interactions with the Frappe workload container (pebble, filesystem,
exec) are performed here. No Juju-level state access takes place in this
module; only the container object and CharmState instances are accepted.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import ops

if TYPE_CHECKING:
    from state import CharmState

logger = logging.getLogger(__name__)

# Paths inside the container
BENCH_DIR = "/home/frappe/frappe-bench"
SITES_DIR = f"{BENCH_DIR}/sites"
COMMON_SITE_CONFIG = f"{SITES_DIR}/common_site_config.json"
NGINX_CONF = "/etc/nginx/conf.d/frappe.conf"
NGINX_TEMPLATE = "/templates/nginx/frappe.conf.template"
BENCH_BIN = f"{BENCH_DIR}/env/bin/bench"
GUNICORN_BIN = f"{BENCH_DIR}/env/bin/gunicorn"
NODE_BIN = "/usr/bin/node"
SOCKETIO_JS = f"{BENCH_DIR}/apps/frappe/socketio.js"

SERVICES = [
    "backend",
    "websocket",
    "frontend",
    "queue-short",
    "queue-long",
    "scheduler",
]


class WorkloadError(Exception):
    """Raised when a workload operation fails."""


class FrappeWorkload:
    """Manages the Frappe HRMS workload running inside the pebble container.

    Accepts a :class:`ops.Container` and a :class:`~state.CharmState`
    instance. No Juju state access is performed directly here.
    """

    def __init__(self, container: ops.Container) -> None:
        """Initialise with the pebble container."""
        self._container = container

    @property
    def is_ready(self) -> bool:
        """Return True if pebble is reachable."""
        return self._container.can_connect()

    # ------------------------------------------------------------------
    # Public API - called from charm.py
    # ------------------------------------------------------------------

    def setup_assets(self) -> None:
        """Prepare the runtime environment after pod start.

        The ``sites/`` directory is an ephemeral K8s emptyDir, created as root
        on every pod start. Two things must be done each time:

        1. Chown ``sites/`` to the frappe user so bench can write site configs,
           logs, and the sentinel file.
        2. Recreate the ``sites/assets`` symlink. The rock build moves pre-built
           frontend assets out of ``sites/`` (which would be wiped by the volume
           mount) into ``bench/assets``. Frappe's gunicorn process looks up asset
           manifests relative to ``sites/``, so the symlink must be restored.

        All other setup (ownership of logs/, config/, www-data user, tzdata) is
        handled at rock build time and does not need to be repeated here.
        """
        try:
            self._container.exec(
                ["chown", "frappe:frappe", SITES_DIR],
            ).wait()
        except (ops.pebble.ExecError, ops.pebble.APIError) as exc:
            logger.warning("chown sites/ failed: %s", exc)

        assets_link = f"{SITES_DIR}/assets"
        assets_target = f"{BENCH_DIR}/assets"
        try:
            self._container.exec(
                [
                    "bash",
                    "-c",
                    f"test -e {assets_link} || ln -s {assets_target} {assets_link}",
                ],
            ).wait()
        except (ops.pebble.ExecError, ops.pebble.APIError) as exc:
            logger.warning("Failed to create assets symlink: %s", exc)

    def configure(self, state: CharmState) -> bool:
        """Write all configuration files and update the pebble layer.

        Returns:
            True if any configuration file changed (signals that a restart
            of the workload services is required).
        """
        common_changed = self._write_common_site_config(state)
        nginx_changed = self._write_nginx_config(state)
        self._update_pebble_layer(state)
        return common_changed or nginx_changed

    def site_exists(self, site_name: str) -> bool:
        """Return True if the Frappe site is fully initialised.

        We check for a sentinel file written at the very end of
        :meth:`create_site` so that a mid-creation failure causes
        ``site_exists`` to return False and the next reconcile retries.
        """
        try:
            self._container.exec(
                ["test", "-f", f"{SITES_DIR}/{site_name}/.charm_ready"],
                user="frappe",
            ).wait()
            return True
        except ops.pebble.ExecError:
            return False

    def create_site(self, state: CharmState) -> None:
        """Create a new Frappe site and install the erpnext and hrms apps.

        The postgresql-k8s charm (data-platform-libs) provisions a dedicated
        PostgreSQL role and database for the application.

        Site creation steps:

        1. Remove the previous (partial) site directory if it exists.
        2. Run ``bench new-site --no-setup-db --db-type postgres`` to bootstrap
           Frappe DB schema and install the ``frappe`` app.
        3. Install the ``erpnext`` app (required by HRMS v16).
        4. Install the ``hrms`` app.
        5. Write a sentinel file so :meth:`site_exists` reports success.

        Raises:
            WorkloadError: If any bench command fails.
        """
        assert state.database is not None, "Database config must be available"  # noqa: S101
        db = state.database

        # 1. Remove existing (partial) site directory.
        site_dir = f"{SITES_DIR}/{state.site_name}"
        try:
            self._container.exec(["rm", "-rf", site_dir]).wait()
        except (ops.pebble.ExecError, ops.pebble.APIError) as exc:
            raise WorkloadError(f"Failed to remove old site dir: {exc}") from exc

        # 2. Bootstrap Frappe DB schema via bench new-site --no-setup-db.
        #    --no-setup-db: skip PostgreSQL role/database creation (already done
        #    by postgresql-k8s charm); just import framework schema and install frappe.
        logger.info(
            "Creating Frappe site %r via bench new-site --no-setup-db",
            state.site_name,
        )
        try:
            stdout, _ = self._container.exec(
                [
                    BENCH_BIN,
                    "new-site",
                    "--no-setup-db",
                    "--db-type",
                    "postgres",
                    "--db-host",
                    db.host,
                    "--db-port",
                    str(db.port),
                    "--db-name",
                    db.database,
                    "--db-user",
                    db.user,
                    "--db-password",
                    db.password,
                    "--admin-password",
                    state.admin_password,
                    state.site_name,
                ],
                working_dir=BENCH_DIR,
                user="frappe",
                timeout=1200,
            ).wait_output()
            logger.info("bench new-site: %s", stdout[:3000])
        except ops.pebble.ExecError as exc:
            raise WorkloadError(f"Failed to create site {state.site_name!r}: {exc}") from exc

        # 3. Install ERPNext (required by HRMS v16).
        logger.info("Installing erpnext app on site %r", state.site_name)
        try:
            stdout, _ = self._container.exec(
                [BENCH_BIN, "--site", state.site_name, "install-app", "erpnext"],
                working_dir=BENCH_DIR,
                user="frappe",
                timeout=1200,
            ).wait_output()
            logger.info("install-app erpnext: %s", stdout[:3000])
        except ops.pebble.ExecError as exc:
            raise WorkloadError(
                f"Failed to install erpnext app on {state.site_name!r}: {exc}"
            ) from exc

        # 4. Install the hrms app.
        logger.info("Installing hrms app on site %r", state.site_name)
        try:
            stdout, _ = self._container.exec(
                [BENCH_BIN, "--site", state.site_name, "install-app", "hrms"],
                working_dir=BENCH_DIR,
                user="frappe",
                timeout=600,
            ).wait_output()
            logger.info("install-app hrms: %s", stdout[:3000])
        except ops.pebble.ExecError as exc:
            raise WorkloadError(
                f"Failed to install hrms app on {state.site_name!r}: {exc}"
            ) from exc

        # 5. Mark the site as fully ready so site_exists() returns True.
        self._container.push(
            f"{site_dir}/.charm_ready",
            "1",
            user="frappe",
            make_dirs=True,
        )

    def migrate(self, site_name: str) -> None:
        """Run bench migrate for the site (used on upgrade-charm).

        Raises:
            WorkloadError: If the migration fails.
        """
        logger.info("Running bench migrate for site %r", site_name)
        try:
            stdout, _ = self._container.exec(
                [BENCH_BIN, "--site", site_name, "migrate"],
                working_dir=BENCH_DIR,
                user="frappe",
            ).wait_output()
            logger.info("Migration output: %s", stdout)
        except ops.pebble.ExecError as exc:
            raise WorkloadError(f"Failed to migrate site {site_name!r}: {exc}") from exc

    def start_services(self) -> None:
        """Start any services that are not yet running (no-op if all running)."""
        self._container.autostart()

    def restart_services(self) -> None:
        """Restart all running workload services."""
        services_info = self._container.get_services()
        for name, info in services_info.items():
            if info.is_running():
                self._container.restart(name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_common_site_config(self, state: CharmState) -> bool:
        """Write common_site_config.json. Returns True if content changed."""
        assert state.database is not None  # noqa: S101
        assert state.redis is not None  # noqa: S101

        config = {
            "db_host": state.database.host,
            "db_port": state.database.port,
            "redis_cache": state.redis.url,
            "redis_queue": state.redis.url,
            "redis_socketio": state.redis.url,
            "socketio_port": 9000,
            "serve_default_site": True,
            "developer_mode": 0,
            "auto_email_id": "",
            "mail_login": "",
            "mail_password": "",
            "mail_port": 587,
            "mail_server": "",
            "use_ssl": 0,
        }
        new_content = json.dumps(config, indent=2, sort_keys=True)
        return self._push_if_changed(COMMON_SITE_CONFIG, new_content, make_dirs=True)

    def _write_nginx_config(self, state: CharmState) -> bool:
        """Render and write the nginx config. Returns True if content changed."""
        # server_name uses the external host (ingress IP/hostname) for routing.
        # X-Frappe-Site-Name and file path lookups must use the actual site name
        # (the directory under sites/) so Frappe can find the correct site.
        server_name = state.external_host or state.site_name

        # Read the nginx config template baked into the rock.
        # If it is missing the rock is broken — raise rather than silently
        # using stale hardcoded config.
        try:
            template = self._container.pull(NGINX_TEMPLATE).read()
        except (ops.pebble.PathError, FileNotFoundError) as exc:
            raise WorkloadError(
                f"Nginx template missing from rock at {NGINX_TEMPLATE}; the rock must be rebuilt."
            ) from exc

        rendered = (
            template.replace("FRAPPE_SERVER_NAME", server_name)
            .replace("FRAPPE_SITE_NAME_HEADER", state.site_name)
            .replace("PROXY_READ_TIMEOUT", str(state.proxy_read_timeout))
            .replace("CLIENT_MAX_BODY_SIZE", state.client_max_body_size)
        )
        return self._push_if_changed(NGINX_CONF, rendered, make_dirs=True)

    def _update_pebble_layer(self, state: CharmState) -> None:
        """Push the pebble layer defining all Frappe HRMS services."""
        layer = self._build_pebble_layer(state)
        self._container.add_layer("frappe-hrms", layer, combine=True)

    def _build_pebble_layer(self, state: CharmState) -> ops.pebble.LayerDict:
        """Construct the pebble layer dict for all Frappe services."""
        bench_env = {
            "BENCH_DIR": BENCH_DIR,
            "FRAPPE_SITE_NAME_HEADER": state.site_name,
        }

        return {
            "summary": "Frappe HRMS",
            "description": "Pebble layer for all Frappe HRMS services",
            "services": {
                "backend": {
                    "override": "replace",
                    "summary": "Frappe gunicorn backend",
                    "command": (
                        f"{GUNICORN_BIN}"
                        f" --chdir={SITES_DIR}"
                        " --bind=0.0.0.0:8000"
                        " --threads=4"
                        " --workers=2"
                        " --worker-class=gthread"
                        " --worker-tmp-dir=/dev/shm"
                        " --timeout=120"
                        " --preload"
                        " frappe.app:application"
                    ),
                    "startup": "enabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                    "on-check-failure": {"backend-up": "restart"},
                },
                "websocket": {
                    "override": "replace",
                    "summary": "Frappe Socket.IO websocket server",
                    "command": f"{NODE_BIN} {SOCKETIO_JS}",
                    "startup": "enabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                    "on-check-failure": {"websocket-up": "restart"},
                },
                "frontend": {
                    "override": "replace",
                    "summary": "Frappe nginx frontend",
                    "command": "nginx -g 'daemon off;'",
                    "startup": "enabled",
                    "on-check-failure": {"frontend-ready": "restart"},
                },
                "queue-short": {
                    "override": "replace",
                    "summary": "Frappe short queue worker",
                    "command": f"{BENCH_BIN} worker --queue short,default",
                    "startup": "enabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                },
                "queue-long": {
                    "override": "replace",
                    "summary": "Frappe long queue worker",
                    "command": f"{BENCH_BIN} worker --queue long,default,short",
                    "startup": "enabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                },
                "scheduler": {
                    "override": "replace",
                    "summary": "Frappe background scheduler",
                    "command": f"{BENCH_BIN} schedule",
                    "startup": "enabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                },
            },
            "checks": {
                # Readiness check: used as K8s readiness probe.
                # level=ready is intentional here (level=alive is prohibited).
                "frontend-ready": {
                    "override": "replace",
                    "level": "ready",
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                    "tcp": {"port": 8080},
                },
                # Internal checks (no level) coupled to service auto-restart.
                "backend-up": {
                    "override": "replace",
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                    "tcp": {"port": 8000},
                },
                "websocket-up": {
                    "override": "replace",
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                    "tcp": {"port": 9000},
                },
            },
        }

    def _push_if_changed(self, path: str, content: str, *, make_dirs: bool = False) -> bool:
        """Push content to a container path only if it differs from current.

        Returns True if the content was updated.
        """
        try:
            current = self._container.pull(path).read()
            if current == content:
                return False
        except (ops.pebble.PathError, FileNotFoundError):
            pass

        self._container.push(path, content, make_dirs=make_dirs)
        return True
