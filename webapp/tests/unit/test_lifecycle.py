"""Test connection handling, liveness and suspension recovery."""

import time

import pytest
from asgi_lifespan import LifespanManager

from app import dependencies
from app.config import describe_database_url


def test_health_live(test_client):
    """Liveness endpoint answers without touching the database."""
    response = test_client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgresql://webapp:s3cret@db.example.com:5432/windburglr?sslmode=require",
            "db.example.com:5432/windburglr",
        ),
        ("postgres://user:pw@host/db", "host/db"),
        ("postgresql://webapp@/windburglr_dev", "(local socket)/windburglr_dev"),
    ],
)
def test_describe_database_url_omits_credentials(database_url, expected):
    description = describe_database_url(database_url)
    assert description == expected
    assert "s3cret" not in description
    assert "pw" not in description


@pytest.mark.asyncio
async def test_pg_connection_not_opened_once_manager_exists(monkeypatch):
    """Requests after the first must not open (and leak) a listener connection."""
    connects: list[str] = []

    async def fake_connect(database_url):
        connects.append(database_url)
        return object()

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    monkeypatch.setattr(dependencies.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(dependencies, "_pg_manager", None)

    assert await dependencies.get_pg_connection() is not None
    assert len(connects) == 1

    monkeypatch.setattr(dependencies, "_pg_manager", object())
    for _ in range(3):
        assert await dependencies.get_pg_connection() is None
    assert len(connects) == 1


@pytest.mark.asyncio
async def test_resumption_marks_cache_stale(monkeypatch):
    """While the app is running, the resumption callback marks cached stations stale."""
    from main import app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_POOL_URL", raising=False)
    dependencies.reset_dependencies()

    async with LifespanManager(app):
        cache_backend = await dependencies.get_cache_backend()
        await cache_backend.add_observation("CYTZ", (time.time(), 270, 12, 15))
        await app.state.suspension_detector._handle_resumption()
        assert await cache_backend.is_station_stale("CYTZ")

    dependencies.reset_dependencies()
