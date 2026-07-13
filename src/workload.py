# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Frappe HRMS workload operations."""

import json
import logging

import ops

from state import CharmState

logger = logging.getLogger(__name__)

SITE_NAME = "frappe-hrms"
BENCH_DIR = "/home/frappe/frappe-bench"
SITES_DIR = f"{BENCH_DIR}/sites"
SITE_DIR = f"{SITES_DIR}/{SITE_NAME}"
COMMON_SITE_CONFIG = f"{SITES_DIR}/common_site_config.json"
BENCH_BIN = f"{BENCH_DIR}/env/bin/bench"
GUNICORN_BIN = f"{BENCH_DIR}/env/bin/gunicorn"
NODE_BIN = "/bin/node"
SOCKETIO_JS = f"{BENCH_DIR}/apps/frappe/socketio.js"

SERVICES = [
    "backend",
    "websocket",
    "frontend",
    "queue-short",
    "queue-long",
    "scheduler",
]

CHECKS = [
    "frontend-ready",
    "backend-up",
    "websocket-up",
]


class WorkloadError(Exception):
    """Raised when a workload operation fails."""


class FrappeWorkload:
    """Manages the Frappe HRMS workload running inside the pebble container."""

    def __init__(self, container: ops.Container) -> None:
        """Initialise with the pebble container."""
        self._container = container

    @staticmethod
    def _truncate_output_tail(output: str | None, max_chars: int = 10000) -> str | None:
        """Truncate output to the last N characters if it exceeds the limit.

        Args:
            output: The output string to potentially truncate.
            max_chars: Maximum number of characters to keep (default: 10000).

        Returns:
            None if output is None, the full output if it has <= max_chars,
            otherwise the last max_chars.
        """
        if output is None:
            return None
        if len(output) > max_chars:
            return output[-max_chars:]
        return output

    def setup_assets(self) -> None:
        """Prepare the mounted site data directory after pod start.

        Only ``sites/<site>`` is a persistent volume; Kubernetes mounts it
        owned by root, so it must be chowned to the ``frappe`` user before
        bench can write the site into it.

        Raises:
            WorkloadError: If the volume cannot be chowned.
        """
        try:
            self._container.exec(
                ["chown", "frappe:frappe", SITE_DIR],
                timeout=60,
            ).wait()
        except (ops.pebble.ExecError, ops.pebble.APIError) as exc:
            raise WorkloadError(f"Failed to chown {SITE_DIR} to frappe") from exc

    def configure(self, state: CharmState) -> bool:
        """Write all configuration files and update the pebble layer.

        Returns:
            True if any configuration file changed (signals that a restart
            of the workload services is required).
        """
        common_changed = self._write_common_site_config(state)
        self._update_pebble_layer(state)
        return common_changed

    def required_apps_installed(self) -> bool:
        """Return True when all required apps are installed on the site."""
        installed_apps = set(self._get_installed_apps(SITE_NAME))
        required_apps = {"frappe", "erpnext", "hrms"}
        result = required_apps.issubset(installed_apps)
        if not result:
            logger.info(
                "Required apps not present for site %r: installed=%s, required=%s",
                SITE_NAME,
                installed_apps,
                required_apps,
            )
        return result

    def setup_hrms(self, state: CharmState) -> None:
        """Create a new Frappe site and install the erpnext and hrms apps.

        Args:
            state: The current charm state.

        Raises:
            WorkloadError: If any bench command fails.
        """
        if "frappe" not in self._get_installed_apps(SITE_NAME):
            if not self._site_exists():
                self._run_bench_new_site(state, state.admin_password.get_secret_value())
            else:
                logger.error(
                    "Frappe site %r already exists on disk but the frappe app is not "
                    "reported by the database; refusing to recreate the site to avoid "
                    "data loss",
                    SITE_NAME,
                )
        else:
            logger.info("Frappe site %r already exists", SITE_NAME)

        self._write_common_site_config(state)

        installed_apps = self._get_installed_apps(SITE_NAME)
        logger.info(
            "Apps already installed on site %r: %s",
            SITE_NAME,
            ", ".join(installed_apps),
        )

        if "erpnext" not in installed_apps:
            self._install_app(SITE_NAME, "erpnext", timeout=600)
        else:
            logger.info("erpnext app already installed on site %r", SITE_NAME)

        if "hrms" not in installed_apps:
            self._install_app(SITE_NAME, "hrms", timeout=600)
        else:
            logger.info("hrms app already installed on site %r", SITE_NAME)

    def _site_exists(self) -> bool:
        """Return True if the Frappe site has already been bootstrapped.

        The check is based on the ``site_config.json`` marker written by
        ``bench new-site`` on the persistent per-site volume. It deliberately
        does not query the database, so a transient database outage cannot be
        mistaken for a missing site.
        """
        try:
            self._container.exec(
                ["test", "-f", f"{SITE_DIR}/site_config.json"],
                timeout=30,
            ).wait()
            return True
        except ops.pebble.ExecError:
            return False

    def _run_bench_new_site(self, state: CharmState, admin_password: str) -> None:
        """Bootstrap a new Frappe site via bench new-site.

        Args:
            state: The current charm state with database config.
            admin_password: The admin password for the site.

        Raises:
            WorkloadError: If the command fails.
        """
        db = state.database

        logger.info(
            "Creating Frappe site %r via bench new-site --no-setup-db",
            SITE_NAME,
        )
        try:
            stdout, stderr = self._container.exec(
                [
                    BENCH_BIN,
                    "new-site",
                    "--force",
                    "--no-setup-db",
                    "--db-type",
                    "mariadb",
                    "--db-host",
                    db.host,
                    "--db-port",
                    str(db.port),
                    "--db-name",
                    db.database,
                    "--db-user",
                    db.user,
                    "--db-password",
                    db.password.get_secret_value(),
                    "--admin-password",
                    admin_password,
                    SITE_NAME,
                ],
                working_dir=BENCH_DIR,
                user="frappe",
                timeout=1200,
            ).wait_output()
            logger.info("bench new-site: %s", self._truncate_output_tail(stdout))
            if stderr:
                logger.info("bench new-site stderr: %s", self._truncate_output_tail(stderr))
        except ops.pebble.ExecError as exc:
            logger.error(
                "bench new-site failed - stdout: %s, stderr: %s",
                self._truncate_output_tail(exc.stdout),
                self._truncate_output_tail(exc.stderr),
            )
            raise WorkloadError(f"Failed to create site {SITE_NAME!r}") from exc

    def _install_app(
        self,
        site_name: str,
        app_name: str,
        timeout: int = 1200,
    ) -> None:
        """Install a Frappe app on the site via bench install-app.

        Args:
            site_name: The Frappe site name.
            app_name: The app to install (e.g., 'erpnext', 'hrms').
            timeout: Command timeout in seconds (default: 1200).

        Raises:
            WorkloadError: If the command fails.
        """
        logger.info("Installing %s app on site %r", app_name, site_name)
        try:
            result = self._container.exec(
                [BENCH_BIN, "--site", site_name, "install-app", app_name],
                working_dir=BENCH_DIR,
                user="frappe",
                timeout=timeout,
            ).wait_output()
            stdout, stderr = result
            logger.info("install-app %s completed with return code 0", app_name)
            logger.info("install-app %s stdout: %s", app_name, self._truncate_output_tail(stdout))
            if stderr:
                logger.warning(
                    "install-app %s stderr (non-fatal): %s",
                    app_name,
                    self._truncate_output_tail(stderr),
                )

            # Verify the app is actually in the database
            logger.info("Verifying %s app installation by querying database...", app_name)
            installed_apps = self._get_installed_apps(site_name)
            if app_name not in installed_apps:
                logger.warning(
                    "App %r not found in list-apps immediately after install-app completed. "
                    "Apps: %s. This may indicate bench install-app is not atomic.",
                    app_name,
                    installed_apps,
                )
            else:
                logger.info("App %r verified in database", app_name)
        except ops.pebble.ExecError as exc:
            logger.error(
                "install-app %s failed with exit code %s - stdout: %s, stderr: %s",
                app_name,
                exc.exit_code,
                self._truncate_output_tail(exc.stdout),
                self._truncate_output_tail(exc.stderr),
            )
            raise WorkloadError(f"Failed to install {app_name} app on {site_name!r}") from exc

    def _get_installed_apps(self, site_name: str) -> list[str]:
        """Get the list of installed apps for a site.

        Args:
            site_name: The Frappe site name.

        Returns:
            A list of app names, or an empty list if unable to retrieve.

        Raises:
            WorkloadError: If the bench list-apps command fails unexpectedly.
        """
        try:
            stdout, _ = self._container.exec(
                [BENCH_BIN, "--site", site_name, "list-apps"],
                working_dir=BENCH_DIR,
                user="frappe",
                timeout=30,
            ).wait_output()
            # bench list-apps outputs one app per line, commonly as:
            # "<app> <version> <branch>".
            raw_apps = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
            apps = [line.split()[0] for line in raw_apps if line.split()]
            logger.debug(
                "Installed apps for site %r: raw=%s normalized=%s",
                site_name,
                raw_apps,
                apps,
            )
            return apps
        except ops.pebble.ExecError as exc:
            logger.warning(
                "Failed to list apps on site %r: stdout=%s, stderr=%s",
                site_name,
                self._truncate_output_tail(exc.stdout),
                self._truncate_output_tail(exc.stderr),
            )
            return []

    def reconcile_services(self, *, restart: bool = False) -> None:
        """Ensure all workload services are running with the current layer.

        Args:
            restart: When True, restart services that are already running so
                they pick up configuration changes. When False, running
                services are left untouched to avoid needless downtime.

        Any service that is not running is always started.
        """
        if restart:
            logger.info("Configuration changed; restarting services")
        services_info = self._container.get_services()
        for service_name in SERVICES:
            try:
                if (info := services_info.get(service_name)) and info.is_running():
                    if restart:
                        self._container.restart(service_name)
                else:
                    self._container.start(service_name)
            except ops.pebble.Error as exc:
                raise WorkloadError(f"Failed to reconcile service {service_name!r}") from exc

    def services_healthy(self) -> bool:
        """Check if all services are running and all Pebble checks are healthy.

        Returns True only if all defined services exist and are running, and
        every defined Pebble check is up. Returns False if any service is not
        running or any check has not (yet) reached the up state.
        """
        try:
            services = self._container.get_services()
        except ops.pebble.Error as e:
            logger.warning("Failed to get service statuses: %s", e)
            return False

        for service_name in SERVICES:
            service_status = services.get(service_name)
            if not service_status:
                logger.warning("Service %r has no status", service_name)
                return False
            if not service_status.is_running():
                current = getattr(service_status, "current", "unknown")
                logger.warning(
                    "Service %r is not running (current=%s)",
                    service_name,
                    current,
                )
                return False

        try:
            checks = self._container.get_checks()
        except ops.pebble.Error as e:
            logger.warning("Failed to get check statuses: %s", e)
            return False

        for check_name in CHECKS:
            check_info = checks.get(check_name)
            if not check_info:
                logger.warning("Check %r has no status", check_name)
                return False
            if check_info.status != ops.pebble.CheckStatus.UP:
                logger.warning(
                    "Check %r is not up (status=%s)",
                    check_name,
                    check_info.status,
                )
                return False

        return True

    def _write_common_site_config(self, state: CharmState) -> bool:
        """Write common_site_config.json. Returns True if content changed."""
        config = {
            "db_host": state.database.host,
            "db_port": state.database.port,
            "redis_cache": state.redis_url,
            "redis_queue": state.redis_url,
            "redis_socketio": state.redis_url,
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

    def _update_pebble_layer(self, state: CharmState) -> None:
        """Push the pebble layer defining all Frappe HRMS services.

        Adds the layer and replans so that newly defined services and checks
        are registered in the running plan.

        Raises:
            WorkloadError: If updating the pebble plan fails.
        """
        layer = self._build_pebble_layer(state)
        try:
            self._container.add_layer("frappe-hrms", layer, combine=True)
            self._container.replan()
        except ops.pebble.Error as exc:
            raise WorkloadError("Failed to update the pebble plan") from exc

    def _build_pebble_layer(self, state: CharmState) -> ops.pebble.LayerDict:
        """Construct the pebble layer dict for all Frappe services."""
        bench_env = {
            "BENCH_DIR": BENCH_DIR,
            "FRAPPE_SITE_NAME_HEADER": SITE_NAME,
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
                    "startup": "disabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                    "on-check-failure": {"backend-up": "restart"},
                },
                "websocket": {
                    "override": "replace",
                    "summary": "Frappe Socket.IO websocket server",
                    "command": f"{NODE_BIN} {SOCKETIO_JS}",
                    "startup": "disabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                    "on-check-failure": {"websocket-up": "restart"},
                },
                "frontend": {
                    "override": "replace",
                    "summary": "Frappe nginx frontend",
                    "command": "nginx -g 'daemon off;'",
                    "startup": "disabled",
                    "on-check-failure": {"frontend-ready": "restart"},
                },
                "queue-short": {
                    "override": "replace",
                    "summary": "Frappe short queue worker",
                    "command": f"{BENCH_BIN} worker --queue short,default",
                    "startup": "disabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                },
                "queue-long": {
                    "override": "replace",
                    "summary": "Frappe long queue worker",
                    "command": f"{BENCH_BIN} worker --queue long,default,short",
                    "startup": "disabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                },
                "scheduler": {
                    "override": "replace",
                    "summary": "Frappe background scheduler",
                    "command": f"{BENCH_BIN} schedule",
                    "startup": "disabled",
                    "user": "frappe",
                    "working-dir": BENCH_DIR,
                    "environment": bench_env,
                },
            },
            "checks": {
                "frontend-ready": {
                    "override": "replace",
                    "level": "ready",
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                    "tcp": {"port": 8080},
                },
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
