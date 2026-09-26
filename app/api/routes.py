import socket
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request):
    monitor = request.app.state.monitor
    database = monitor.database
    db_status = "connected" if database.check() else ("unconfigured" if not database.settings.database_configured else "unavailable")
    return {"status": "degraded" if monitor.error else "ok", "hostname": socket.gethostname(), "monitor_last_checked": monitor.last_checked, "database": db_status, "database_warning": database.warning, "monitor_warning": monitor.error, "alert_warning": monitor.alerts.warning if monitor.alerts else None}


@router.get("/services")
async def services(request: Request):
    monitor = request.app.state.monitor
    items = [item.model_dump(mode="json") for item in monitor.services]
    counts = {"total": len(items), "running": sum(x["status"] == "RUNNING" for x in items), "stopped": sum(x["status"] == "STOPPED" for x in items)}
    counts["warning"] = counts["total"] - counts["running"] - counts["stopped"]
    return {"services": items, "counts": counts, "last_checked": monitor.last_checked, "monitor_warning": monitor.error, "database_warning": monitor.database.warning, "alert_warning": monitor.alerts.warning if monitor.alerts else None}


@router.get("/services/{service_name}/history")
async def service_history(service_name: str, request: Request, hours: int = 24):
    if hours not in (1, 6, 24, 168):
        raise HTTPException(400, "hours must be 1, 6, 24, or 168")
    history = request.app.state.monitor.database.history(service_name, hours)
    if history is None:
        return {"service_name": service_name, "history": [], "available": False, "message": request.app.state.monitor.database.warning}
    return {"service_name": service_name, "history": history, "available": True, "message": None if history else "No historical data available."}
