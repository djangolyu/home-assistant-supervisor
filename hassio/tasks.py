"""Multible tasks."""
import asyncio
import logging

from .coresys import CoreSysAttributes

_LOGGER = logging.getLogger(__name__)


class Tasks(CoreSysAttributes):
    """Handle Tasks inside HassIO."""

    RUN_UPDATE_SUPERVISOR = 29100
    RUN_UPDATE_ADDONS = 57600

    RUN_RELOAD_ADDONS = 21600
    RUN_RELOAD_SNAPSHOTS = 72000
    RUN_RELOAD_HOST = 72000
    RUN_RELOAD_UPDATER = 21600

    RUN_WATCHDOG_HOMEASSISTANT_DOCKER = 15
    RUN_WATCHDOG_HOMEASSISTANT_API = 300

    def __init__(self, coresys):
        """Initialize Tasks."""
        self.coresys = coresys
        self.jobs = set()
        self._data = {}

    async def load(self):
        """Add Tasks to scheduler."""
        self.jobs.add(self.sys_scheduler.register_task(
            self._update_addons, self.RUN_UPDATE_ADDONS))
        self.jobs.add(self.sys_scheduler.register_task(
            self._update_supervisor, self.RUN_UPDATE_SUPERVISOR))

        self.jobs.add(self.sys_scheduler.register_task(
            self.sys_addons.reload, self.RUN_RELOAD_ADDONS))
        self.jobs.add(self.sys_scheduler.register_task(
            self.sys_updater.reload, self.RUN_RELOAD_UPDATER))
        self.jobs.add(self.sys_scheduler.register_task(
            self.sys_snapshots.reload, self.RUN_RELOAD_SNAPSHOTS))
        self.jobs.add(self.sys_scheduler.register_task(
            self.sys_host.load, self.RUN_RELOAD_HOST))

        self.jobs.add(self.sys_scheduler.register_task(
            self._watchdog_homeassistant_docker,
            self.RUN_WATCHDOG_HOMEASSISTANT_DOCKER))
        self.jobs.add(self.sys_scheduler.register_task(
            self._watchdog_homeassistant_api,
            self.RUN_WATCHDOG_HOMEASSISTANT_API))

        _LOGGER.info("All core tasks are scheduled")

    async def _update_addons(self):
        """Check if an update is available for an addon and update it."""
        tasks = []
        for addon in self.sys_addons.list_addons:
            if not addon.is_installed or not addon.auto_update:
                continue

            if addon.version_installed == addon.last_version:
                continue

            if addon.test_udpate_schema():
                tasks.append(addon.update())
            else:
                _LOGGER.warning(
                    "Addon %s will be ignore, schema tests fails", addon.slug)

        if tasks:
            _LOGGER.info("Addon auto update process %d tasks", len(tasks))
            await asyncio.wait(tasks)

    async def _update_supervisor(self):
        """Check and run update of supervisor hassio."""
        if not self.sys_supervisor.need_update:
            return

        # don't perform an update on beta/dev channel
        if self.sys_dev:
            _LOGGER.warning("Ignore Hass.io update on dev channel!")
            return

        _LOGGER.info("Found new Hass.io version")
        await self.sys_supervisor.update()

    async def _watchdog_homeassistant_docker(self):
        """Check running state of docker and start if they is close."""
        # if Home-Assistant is active
        if not await self.sys_homeassistant.is_initialize() or \
                not self.sys_homeassistant.watchdog:
            return

        # if Home-Assistant is running
        if self.sys_homeassistant.in_progress or \
                await self.sys_homeassistant.is_running():
            return

        _LOGGER.warning("Watchdog found a problem with Home-Assistant docker!")
        await self.sys_homeassistant.start()

    async def _watchdog_homeassistant_api(self):
        """Create scheduler task for montoring running state of API.

        Try 2 times to call API before we restart Home-Assistant. Maybe we had
        a delay in our system.
        """
        retry_scan = self._data.get('HASS_WATCHDOG_API', 0)

        # If Home-Assistant is active
        if not await self.sys_homeassistant.is_initialize() or \
                not self.sys_homeassistant.watchdog:
            return

        # If Home-Assistant API is up
        if self.sys_homeassistant.in_progress or \
                await self.sys_homeassistant.check_api_state():
            return

        # Look like we run into a problem
        retry_scan += 1
        if retry_scan == 1:
            self._data['HASS_WATCHDOG_API'] = retry_scan
            _LOGGER.warning("Watchdog miss API response from Home-Assistant")
            return

        _LOGGER.error("Watchdog found a problem with Home-Assistant API!")
        await self.sys_homeassistant.restart()
        self._data['HASS_WATCHDOG_API'] = 0
