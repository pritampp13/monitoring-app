import asyncio
from datetime import datetime, timezone
from app.database import Database
from app.services.windows_services import discover_kepware_services
from alerts.gmail import GmailStoppedAlert


class ServiceMonitor:
    def __init__(self, database: Database, interval: int, alerts: GmailStoppedAlert | None = None, discoverer=discover_kepware_services):
        self.database, self.interval = database, interval
        self.alerts, self.discoverer = alerts, discoverer
        self.services = []
        self.last_checked: datetime | None = None
        self.error: str | None = None
        self._task: asyncio.Task | None = None
        self._previous_states: dict[str, str] = {}

    async def _restore_previous_states(self) -> None:
        self._previous_states = await asyncio.to_thread(self.database.last_known_statuses)

    async def collect(self) -> None:
        try:
            self.services = await asyncio.to_thread(self.discoverer)
            self.last_checked = datetime.now(timezone.utc)
            self.error = None
            for service in self.services:
                previous = self._previous_states.get(service.service_name)
                if previous == "RUNNING" and service.status == "STOPPED" and self.alerts:
                    await asyncio.to_thread(self.alerts.send, service, previous)
                # Update even if SMTP fails: one state transition means one send attempt.
                self._previous_states[service.service_name] = service.status
            await asyncio.to_thread(self.database.record, self.services)
        except Exception as exc:
            self.error = f"Windows service query failed: {type(exc).__name__}"

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
