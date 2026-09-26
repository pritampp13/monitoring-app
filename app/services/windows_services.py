"""Read-only access to Windows Service Control Manager via CIM."""
import json
import subprocess
from datetime import datetime, timezone

from app.models import ServiceObservation

VALID_STATES = {
    "RUNNING", "STOPPED", "START_PENDING", "STOP_PENDING", "PAUSED",
    "PAUSE_PENDING", "CONTINUE_PENDING",
}
STATE_MAP = {
    "running": "RUNNING", "stopped": "STOPPED", "start pending": "START_PENDING",
    "stop pending": "STOP_PENDING", "paused": "PAUSED", "pause pending": "PAUSE_PENDING",
    "continue pending": "CONTINUE_PENDING",
}


def normalize_status(value: object) -> str:
    text = str(value or "").strip()
    return STATE_MAP.get(text.lower(), text.upper().replace(" ", "_") if text.upper().replace(" ", "_") in VALID_STATES else "UNKNOWN")


def is_kepware_service(raw: dict) -> bool:
    return "kepware" in f"{raw.get('Name', '')} {raw.get('DisplayName', '')}".lower() or "kepserver" in f"{raw.get('Name', '')} {raw.get('DisplayName', '')}".lower()


def _read_services() -> list[dict]:
    command = "Get-CimInstance Win32_Service | Select-Object Name,DisplayName,State,StartMode | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, check=True, timeout=20)
    payload = json.loads(result.stdout or "[]")
    return payload if isinstance(payload, list) else [payload]


def discover_kepware_services(reader=_read_services, checked_at: datetime | None = None) -> list[ServiceObservation]:
    checked_at = checked_at or datetime.now(timezone.utc)
    found = []
    for raw in reader():
        if is_kepware_service(raw):
            found.append(ServiceObservation(
                service_name=raw["Name"], display_name=raw.get("DisplayName") or raw["Name"],
                status=normalize_status(raw.get("State")), startup_type=raw.get("StartMode"), last_checked=checked_at,
            ))
    return sorted(found, key=lambda item: item.display_name.lower())
