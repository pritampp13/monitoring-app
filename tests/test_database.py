from app.config import Settings
from app.database import Database


def test_unconfigured_database_is_safe():
    db = Database(Settings(mssql_server="", mssql_database=""))
    assert not db.check()
    assert "not configured" in db.warning


def test_unavailable_database_is_safe():
    db = Database(Settings(mssql_server="not-a-real-host", mssql_database="none"))
    assert not db.check()
    assert "unavailable" in db.warning
