import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import logging
from app.database import Database
from app.services.windows_services import discover_kepware_services
from alerts.gmail import GmailStoppedAlert

logger = logging.getLogger(__name__)
# Transitional (*_PENDING) and UNKNOWN states never replace the last stable state, so
# RUNNING -> STOP_PENDING -> STOPPED still counts as one RUNNING -> STOPPED transition.
STABLE_STATES = {"RUNNING", "STOPPED", "PAUSED"}
RECENT_CHANGES_PER_SERVICE = 2000


class ServiceMonitor:
    def __init__(self, database: Database, interval: int, alerts: GmailStoppedAlert | None = None, discoverer=discover_kepware_services):
        self.database, self.interval = database, interval
        self.alerts, self.discoverer = alerts, discoverer
        self.services = []
        self.last_checked: datetime | None = None
        self.error: str | None = None
        self._task: asyncio.Task | None = None
        self._previous_states: dict[str, str] = {}
        self._alert_tasks: set[asyncio.Task] = set()
        # Genuine state-change points observed by this process; history fallback when MSSQL is unavailable.
        self._recent: dict[str, deque] = {}

    async def _restore_previous_states(self) -> None:
        self._previous_states = await asyncio.to_thread(self.database.last_known_statuses)

    async def collect(self) -> None:
        try:
            self.services = await asyncio.to_thread(self.discoverer)
            self.last_checked = datetime.now(timezone.utc)
            if self.error:
                logger.info("Windows service query recovered")
            self.error = None
            for service in self.services:
                self._remember(service)
                if service.status not in STABLE_STATES:
                    continue
                previous = self._previous_states.get(service.service_name)
                if previous == "RUNNING" and service.status == "STOPPED" and self.alerts:
                    self._dispatch_alert(service, previous)
                # Update even if SMTP fails or alerts are OFF: one state transition means one send attempt.
                self._previous_states[service.service_name] = service.status
            await asyncio.to_thread(self.database.record, self.services)
        except Exception as exc:
            if not self.error:
                logger.warning("Windows service query failed (%s)", type(exc).__name__)
            self.error = f"Windows service query failed: {type(exc).__name__}"

    def _remember(self, service) -> None:
        changes = self._recent.setdefault(service.service_name, deque(maxlen=RECENT_CHANGES_PER_SERVICE))
        if not changes or changes[-1]["status"] != service.status:
            changes.append({"status": service.status, "startup_type": service.startup_type, "checked_at": service.last_checked})

    def recent_history(self, service_name: str, hours: int) -> list[dict]:
        """In-memory change points newest first, plus the last change before the window (the state at its start)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        changes = list(self._recent.get(service_name, ()))
        inside = [x for x in changes if x["checked_at"] >= cutoff]
        before = [x for x in changes if x["checked_at"] < cutoff][-1:]
        return [{"status": x["status"], "startup_type": x["startup_type"], "checked_at": x["checked_at"].isoformat().replace("+00:00", "Z"), "hostname": None}
                for x in reversed(before + inside)]

    def _dispatch_alert(self, service, previous: str) -> None:
        """Email delivery runs in the background so slow or failing SMTP never delays polling."""
        task = asyncio.create_task(self._send_alert(service, previous))
        self._alert_tasks.add(task)
        task.add_done_callback(self._alert_tasks.discard)

    async def _send_alert(self, service, previous: str) -> None:
        try:
            await asyncio.to_thread(self.alerts.send, service, previous)
        except Exception as exc:
            logger.warning("STOPPED alert dispatch failed for %s (%s)", service.service_name, type(exc).__name__)

    async def wait_for_alerts(self) -> None:
        if self._alert_tasks:
            await asyncio.gather(*list(self._alert_tasks), return_exceptions=True)

    async def run(self) -> None:
        while True:
            await self.collect()
            await asyncio.sleep(self.interval)

    async def start(self) -> None:
        await self._restore_previous_states()
        await self.collect()
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
        if self._alert_tasks:
            await asyncio.wait(list(self._alert_tasks), timeout=20)
