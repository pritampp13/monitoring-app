"""Persistent email-alert kill switch. It gates email delivery only, never monitoring."""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "alert_settings.json"


class EmailAlertSwitch:
    def __init__(self, default_enabled: bool = True, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.enabled = default_enabled
        self.updated_at: str | None = None
        self.warning: str | None = None
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data.get("email_alerts_enabled"), bool):
                self.enabled = data["email_alerts_enabled"]
                self.updated_at = data.get("updated_at")
        except Exception as exc:
            self.warning = f"Email alert switch file unreadable ({type(exc).__name__}); using EMAIL_ALERTS_ENABLED."

    def set(self, enabled: bool) -> None:
        """Change the switch in memory first, then persist atomically; a write failure keeps the new value."""
        with self._lock:
            self.enabled = enabled
            self.updated_at = datetime.now(timezone.utc).isoformat()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_suffix(".tmp")
                temp.write_text(json.dumps({"email_alerts_enabled": enabled, "updated_at": self.updated_at}), encoding="utf-8")
                os.replace(temp, self.path)
                self.warning = None
            except OSError as exc:
                self.warning = f"Email alert switch could not be saved ({type(exc).__name__}); it will reset on restart."
            logger.info("Email alerts switched %s from the dashboard", "ON" if enabled else "OFF")
