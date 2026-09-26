from datetime import datetime, timezone
from app.services.windows_services import discover_kepware_services, normalize_status


def test_parses_windows_states():
    assert normalize_status("Running") == "RUNNING"
    assert normalize_status("Stop Pending") == "STOP_PENDING"
    assert normalize_status("nonsense") == "UNKNOWN"


def test_discovers_only_kepware_services():
    rows = [
        {"Name": "KepwareServerV7", "DisplayName": "Kepware Server Runtime", "State": "Running", "StartMode": "Auto"},
        {"Name": "Spooler", "DisplayName": "Print Spooler", "State": "Running", "StartMode": "Auto"},
    ]
    result = discover_kepware_services(lambda: rows, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert len(result) == 1 and result[0].service_name == "KepwareServerV7"


def test_missing_service_is_not_fabricated():
    assert discover_kepware_services(lambda: []) == []
