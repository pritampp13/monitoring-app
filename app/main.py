from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api.routes import router
from app.config import get_settings
from app.database import Database
from app.monitoring.monitor import ServiceMonitor
from alerts.gmail import GmailStoppedAlert

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def configure_logging() -> None:
    """Write operational failures locally; alert code never includes credentials in logs."""
    log_dir = ROOT.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_dir / "monitor.log", encoding="utf-8")],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    app.state.monitor = ServiceMonitor(Database(settings), settings.monitor_interval_seconds, GmailStoppedAlert(settings))
    await app.state.monitor.start()
    yield
    await app.state.monitor.stop()


app = FastAPI(title="Kepware Server Monitor", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.include_router(router)


def asset_version() -> str:
    """Changes whenever app.js/style.css change, so browsers never mix new HTML with cached old assets."""
    return str(int(max((ROOT / "static" / name).stat().st_mtime for name in ("app.js", "style.css"))))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html", {"interval": get_settings().monitor_interval_seconds, "version": asset_version()})
