from datetime import datetime
from pydantic import BaseModel


class ServiceObservation(BaseModel):
    service_name: str
    display_name: str
    status: str
    startup_type: str | None = None
    last_checked: datetime


class HealthResponse(BaseModel):
    status: str
    hostname: str
    monitor_last_checked: datetime | None
    database: str
    database_warning: str | None = None
