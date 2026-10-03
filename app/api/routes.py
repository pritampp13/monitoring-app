import asyncio
import socket
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class EmailAlertToggle(BaseModel):
    enabled: bool


def _alert_status(monitor) -> dict:
    return monitor.alerts.status() if monitor.alerts else {"enabled": False, "configured": False, "warning": "Email alerting is not initialised."}


def _require_local_same_origin(request: Request) -> None:
    """No login exists (localhost-only v1), so block cross-site and DNS-rebinding writes."""
    host = request.headers.get("host", "")
    if (urlsplit(f"//{host}").hostname or "") not in LOCAL_HOSTS:
        raise HTTPException(403, "Alert settings can only be changed from the local dashboard.")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != host:
        raise HTTPException(403, "Alert settings can only be changed from the local dashboard.")


@router.get("/health")
async def health(request: Request):
    monitor = request.app.state.monitor
    database = monitor.database
    connected = await asyncio.to_thread(database.check)
    db_status = "connected" if connected else ("unconfigured" if not database.settings.database_configured else "unavailable")
    return {"status": "degraded" if monitor.error else "ok", "hostname": socket.gethostname(), "monitor_last_checked": monitor.last_checked, "database": db_status, "database_warning": database.warning, "monitor_warning": monitor.error, "alert_warning": monitor.alerts.warning if monitor.alerts else None, "email_alerts": _alert_status(monitor)}


@router.get("/services")
async def services(request: Request):
    monitor = request.app.state.monitor
    items = [item.model_dump(mode="json") for item in monitor.services]
    counts = {"total": len(items), "running": sum(x["status"] == "RUNNING" for x in items), "stopped": sum(x["status"] == "STOPPED" for x in items)}
    counts["warning"] = counts["total"] - counts["running"] - counts["stopped"]
    return {"services": items, "counts": counts, "last_checked": monitor.last_checked, "monitor_warning": monitor.error, "database_warning": monitor.database.warning, "alert_warning": monitor.alerts.warning if monitor.alerts else None, "email_alerts": _alert_status(monitor)}


@router.get("/alerts")
async def alerts(request: Request):
    return _alert_status(request.app.state.monitor)


@router.put("/alerts/email")
async def set_email_alerts(toggle: EmailAlertToggle, request: Request):
    """Email kill switch: affects email delivery only; monitoring, history and the dashboard keep running."""
    _require_local_same_origin(request)
    monitor = request.app.state.monitor
    if not monitor.alerts:
        raise HTTPException(503, "Email alerting is not initialised.")
    await asyncio.to_thread(monitor.alerts.switch.set, toggle.enabled)
    return _alert_status(monitor)


@router.get("/history")
async def all_history(request: Request, hours: int = 24):
    """Every service's history in one request; feeds the dashboard timelines and hover graphs."""
    if hours not in (1, 6, 24, 168):
        raise HTTPException(400, "hours must be 1, 6, 24, or 168")
    monitor = request.app.state.monitor
    history = await asyncio.to_thread(monitor.database.history_all, hours)
    if history is None:
        message = (monitor.database.warning or "Persisted history is unavailable.") + " Showing state changes observed since the monitor started."
        return {"hours": hours, "services": {s.service_name: monitor.recent_history(s.service_name, hours) for s in monitor.services}, "available": False, "source": "memory", "message": message}
    return {"hours": hours, "services": history, "available": True, "source": "database", "message": None}


@router.get("/services/{service_name}/history")
async def service_history(service_name: str, request: Request, hours: int = 24):
    if hours not in (1, 6, 24, 168):
        raise HTTPException(400, "hours must be 1, 6, 24, or 168")
    monitor = request.app.state.monitor
    history = await asyncio.to_thread(monitor.database.history, service_name, hours)
    if history is None:
        recent = monitor.recent_history(service_name, hours)
        message = monitor.database.warning or "Persisted history is unavailable."
        if recent:
            message += " Showing state changes observed since the monitor started."
        return {"service_name": service_name, "history": recent, "available": False, "source": "memory", "message": message}
    return {"service_name": service_name, "history": history, "available": True, "source": "database", "message": None if history else "No historical data available."}
