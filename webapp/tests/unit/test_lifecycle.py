"""Test startup and shutdown, the listener's reconnection, cache hydration and liveness."""

import asyncio
import time
from contextlib import asynccontextmanager, nullcontext

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.cache.abc import CacheBackend
from app.config import describe_database_url
from app.database import create_db_pool
from app.services.cache_hydration import CacheHydrator
from app.services.notifications import PostgresNotificationManager
from app.services.station import StationService
from app.services.watchdog import WatchdogService
from app.services.websocket import WebSocketManager
from app.services.wind_data import WindDataService
from app.utils.suspension_detector import SuspensionDetector
from tests.conftest import MockConnection, MockListenerConnection, MockPool


async def wait_for(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail("Timed out waiting for condition")
        await asyncio.sleep(0.01)


def client_for(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def wind_queries(mock_manager) -> int:
    return len(mock_manager.get_recorded_queries(contains="get_wind_data_by_station_range"))


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
async def test_create_db_pool_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_POOL_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await create_db_pool()


@pytest.mark.asyncio
async def test_services_on_app_state_after_startup(make_mock_app, mock_test_db_manager):
    """Startup builds every service once, before any request, and starts the listener."""
    app = make_mock_app()
    async with LifespanManager(app):
        state = app.state
        assert isinstance(state.db_pool, MockPool)
        assert isinstance(state.cache_backend, CacheBackend)
        assert isinstance(state.station_service, StationService)
        assert isinstance(state.wind_service, WindDataService)
        assert isinstance(state.watchdog_service, WatchdogService)
        assert isinstance(state.websocket_manager, WebSocketManager)
        assert isinstance(state.pg_manager, PostgresNotificationManager)
        assert isinstance(state.cache_hydrator, CacheHydrator)
        assert isinstance(state.suspension_detector, SuspensionDetector)

        # Services share the cache and pool
        assert state.wind_service.cache is state.cache_backend
        assert state.wind_service.pool is state.db_pool
        assert state.pg_manager.cache_backend is state.cache_backend
        assert state.watchdog_service.websocket_manager is state.websocket_manager

        # The listener connected at startup, not on a first request
        assert mock_test_db_manager.query_count > 0  # watchdog loaded scraper status
        assert state.pg_manager.connect_attempts == 1
        assert state.pg_manager.is_pg_listener_healthy
        assert not state.pg_manager.monitor_task.done()

        async with client_for(app) as client:
            assert (await client.get("/api/wind")).status_code == 200
        assert state.pg_manager.connect_attempts == 1


@pytest.mark.asyncio
async def test_listener_retries_after_failed_connect(
    make_mock_app, mock_test_db_manager
):
    """A failed connect at startup doesn't fail startup; the listener keeps retrying."""
    attempts = 0

    async def flaky_connect():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("connection refused")
        return MockListenerConnection(mock_test_db_manager)

    app = make_mock_app(connect_listener=flaky_connect, listener_retry_delay=0.01)
    async with LifespanManager(app):
        pg_manager = app.state.pg_manager
        # Startup completed with the listener down
        async with client_for(app) as client:
            assert (await client.get("/health/live")).status_code == 200

        await wait_for(lambda: pg_manager.is_pg_listener_healthy)
        assert attempts == 3


@pytest.mark.asyncio
async def test_slow_listener_connect_does_not_block_startup(make_mock_app):
    """A connect that hangs is abandoned after listener_connect_timeout."""
    never = asyncio.Event()

    async def hanging_connect():
        await never.wait()

    app = make_mock_app(
        connect_listener=hanging_connect,
        listener_connect_timeout=0.05,
        listener_retry_delay=10,
    )
    started = time.monotonic()
    async with LifespanManager(app):
        assert time.monotonic() - started < 1
        assert not app.state.pg_manager.is_pg_listener_healthy
        assert not app.state.pg_manager.monitor_task.done()


@pytest.mark.asyncio
async def test_listener_reconnects_and_refreshes_cache(
    make_mock_app, mock_test_db_manager
):
    """When the listener's connection drops, it reconnects and rehydrates the cache,
    since notifications sent in between were missed."""
    connections: list[MockListenerConnection] = []

    async def connect():
        connections.append(MockListenerConnection(mock_test_db_manager))
        return connections[-1]

    mock_test_db_manager.create_test_data("CYTZ")
    app = make_mock_app(
        connect_listener=connect,
        listener_retry_delay=0.01,
        cache_hydration_hours=24,
    )
    async with LifespanManager(app):
        state = app.state
        await state.cache_hydrator.task
        assert len(connections) == 1

        connections[0].drop()
        await wait_for(lambda: state.pg_manager.pg_listener is not connections[0])
        await wait_for(lambda: state.pg_manager.is_pg_listener_healthy)
        assert len(connections) == 2

        # Rehydrated: fresh data again, no longer stale
        await state.cache_hydrator.task
        assert not await state.cache_backend.is_station_stale("CYTZ")
        assert state.cache_hydrator.last_run["state"] == "done"


@pytest.mark.asyncio
async def test_resumption_marks_cache_stale(make_mock_app):
    """While the app is running, the resumption callback marks cached stations stale."""
    app = make_mock_app()
    async with LifespanManager(app):
        cache_backend = app.state.cache_backend
        await cache_backend.add_observation("CYTZ", (time.time(), 270, 12, 15))
        await app.state.suspension_detector._handle_resumption()
        assert await cache_backend.is_station_stale("CYTZ")


@pytest.mark.asyncio
async def test_resumption_rehydrates_cache(make_mock_app, mock_test_db_manager):
    mock_test_db_manager.create_test_data("CYTZ")
    app = make_mock_app(cache_hydration_hours=24)
    async with LifespanManager(app):
        hydrator = app.state.cache_hydrator
        first_run = hydrator.task
        await first_run
        queries = wind_queries(mock_test_db_manager)

        await app.state.suspension_detector._handle_resumption()
        assert hydrator.task is not first_run
        await hydrator.task
        assert wind_queries(mock_test_db_manager) > queries
        assert not await app.state.cache_backend.is_station_stale("CYTZ")


@pytest.mark.asyncio
async def test_hydration_fills_cache(make_mock_app, mock_test_db_manager):
    """Startup loads the default station and the other scraped stations, so the
    first page load is a cache hit."""
    mock_test_db_manager.create_test_data("CYTZ", days=2)
    mock_test_db_manager.create_test_data("CYYZ", days=2)
    app = make_mock_app(cache_hydration_hours=24)
    async with LifespanManager(app):
        hydrator = app.state.cache_hydrator
        await hydrator.task

        assert hydrator.last_run["state"] == "done"
        assert hydrator.last_run["stations"] == ["CYTZ", "CYYZ"]
        # One day of observations a minute apart, per station
        assert 2 * (24 * 60 - 1) <= hydrator.last_run["observations"] <= 2 * 24 * 60
        stats = await app.state.cache_backend.get_cache_stats()
        assert stats["stations_cached"] == 2
        # Hydration isn't a request: no misses counted
        assert stats["cache_miss_count"] == 0

        queries = wind_queries(mock_test_db_manager)
        async with client_for(app) as client:
            for url in ["/api/wind?hours=3", "/api/wind", "/api/wind?stn=CYYZ&hours=24"]:
                response = await client.get(url)
                assert response.status_code == 200
                assert response.json()["cache_hit"], url
                assert response.json()["winddata"]
            health = (await client.get("/health")).json()
        assert wind_queries(mock_test_db_manager) == queries
        assert health["cache_hydration"]["state"] == "done"


class GatedMockPool(MockPool):
    """Holds the first wind data query (hydration's) until `gate` is set."""

    def __init__(self, mock_manager):
        super().__init__(mock_manager)
        self.gate = asyncio.Event()
        self.held = asyncio.Event()

    @asynccontextmanager
    async def acquire(self):
        yield GatedConnection(self)


class GatedConnection(MockConnection):
    def __init__(self, pool: GatedMockPool):
        super().__init__(pool.mock_manager)
        self.pool = pool

    async def fetch(self, query, *args):
        if "get_wind_data_by_station_range" in query and not self.pool.held.is_set():
            self.pool.held.set()
            await self.pool.gate.wait()
        return await super().fetch(query, *args)


@pytest.mark.asyncio
async def test_request_during_hydration_served_from_database(
    make_mock_app, mock_test_db_manager
):
    """A request arriving mid-hydration queries the database, and the two writes
    leave the cache consistent."""
    test_data = mock_test_db_manager.create_test_data("CYTZ", days=2)
    pool = GatedMockPool(mock_test_db_manager)
    app = make_mock_app(
        open_db_pool=lambda: nullcontext(pool), cache_hydration_hours=24
    )
    async with LifespanManager(app), client_for(app) as client:
        hydrator = app.state.cache_hydrator
        await asyncio.wait_for(pool.held.wait(), timeout=2)
        assert not hydrator.task.done()

        # Meanwhile, live page requests go to the database
        response = await client.get("/api/wind?hours=3")
        assert response.status_code == 200
        body = response.json()
        assert not body["cache_hit"]
        assert len(body["winddata"]) == 3 * 60 - 1

        # A live observation arrives too
        observation = (time.time(), 90, 7, 9)
        await app.state.cache_backend.add_observation("CYTZ", observation)

        pool.gate.set()
        await hydrator.task
        assert hydrator.last_run["state"] == "done"

        cache_backend = app.state.cache_backend
        cached = cache_backend.wind_data_cache["CYTZ"]
        timestamps = [row[0] for row in cached]
        assert timestamps == sorted(set(timestamps)), "cache unsorted or duplicated"
        expected = {
            obs["update_time"].timestamp()
            for obs in test_data
            if obs["update_time"].timestamp() >= time.time() - 24 * 3600
        }
        assert expected <= set(timestamps)
        assert cached[-1] == observation

        response = await client.get("/api/wind?hours=24")
        assert response.json()["cache_hit"]


@pytest.mark.asyncio
async def test_hydration_errors_are_not_fatal(make_mock_app, mock_test_db_manager):
    class FailingConnection(MockConnection):
        async def fetch(self, query, *args):
            if "get_wind_data_by_station_range" in query:
                raise ConnectionError("database went away")
            return await super().fetch(query, *args)

    class FailingPool(MockPool):
        @asynccontextmanager
        async def acquire(self):
            yield FailingConnection(self.mock_manager)

    app = make_mock_app(
        open_db_pool=lambda: nullcontext(FailingPool(mock_test_db_manager)),
        cache_hydration_hours=24,
    )
    async with LifespanManager(app), client_for(app) as client:
        await app.state.cache_hydrator.task
        assert app.state.cache_hydrator.last_run["stations"] == []
        assert (await client.get("/health/live")).status_code == 200


@pytest.mark.asyncio
async def test_clean_shutdown(make_mock_app, mock_test_db_manager):
    """Shutdown stops the background tasks and closes the listener, then the pool."""
    events: list[str] = []

    class RecordingListener(MockListenerConnection):
        async def close(self):
            events.append("listener closed")
            await super().close()

    async def connect():
        return RecordingListener(mock_test_db_manager)

    @asynccontextmanager
    async def open_pool():
        events.append("pool opened")
        yield MockPool(mock_test_db_manager)
        events.append("pool closed")

    mock_test_db_manager.create_test_data("CYTZ")
    app = make_mock_app(
        open_db_pool=open_pool, connect_listener=connect, cache_hydration_hours=24
    )
    async with LifespanManager(app):
        state = app.state
        pg_manager = state.pg_manager
        monitor_task = pg_manager.monitor_task
        hydration_task = state.cache_hydrator.task
        assert state.suspension_detector.is_monitoring

    assert events == ["pool opened", "listener closed", "pool closed"]
    assert monitor_task.done()
    assert hydration_task.done()
    assert pg_manager.pg_listener is None
    assert not pg_manager.is_pg_listener_healthy
    assert not state.suspension_detector.is_monitoring
    assert state.suspension_detector.monitor_task.done()
    assert state.websocket_manager.active_connections == {}


@pytest.mark.asyncio
async def test_shutdown_cancels_running_hydration(make_mock_app, mock_test_db_manager):
    pool = GatedMockPool(mock_test_db_manager)
    app = make_mock_app(
        open_db_pool=lambda: nullcontext(pool), cache_hydration_hours=24
    )
    async with LifespanManager(app):
        await asyncio.wait_for(pool.held.wait(), timeout=2)
        task = app.state.cache_hydrator.task
    assert task.cancelled()
    assert app.state.cache_hydrator.last_run["state"] == "cancelled"
