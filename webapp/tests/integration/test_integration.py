from asyncio import sleep
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from httpx_ws import aconnect_ws


class TestIntegration:
    """Integration tests combining multiple components with sync fixtures."""

    @pytest.mark.anyio
    async def test_health(self, integration_client):
        """Test health endpoint."""
        response = await integration_client.get("/health")
        assert response.status_code == 200
        health_data = response.json()
        assert health_data["status"] == "healthy"
        assert health_data["database"] == "connected"
        assert health_data["websocket"] == "no_connections"
        assert health_data["postgresql_listener"] == "healthy"

    @pytest.mark.anyio
    async def test_multiple_stations(self, integration_client):
        """Test multiple stations."""
        # Test CYTZ
        response = await integration_client.get("/api/wind?stn=CYTZ&hours=12")
        assert response.status_code == 200
        assert response.json()["station"] == "CYTZ"

        # Test CYYZ
        response = await integration_client.get("/api/wind?stn=CYYZ&hours=12")
        assert response.status_code == 200
        assert response.json()["station"] == "CYYZ"

    @pytest.mark.anyio
    async def test_timezone_handling(
        self, integration_client, test_db_manager, sample_stations
    ):
        """Test timezone handling across different stations."""
        # Test Toronto station - should return America/Toronto with real database
        await test_db_manager.create_test_stations(sample_stations)
        response = await integration_client.get("/api/wind?stn=CYTZ&hours=12")
        data = response.json()
        assert data["timezone"] == "America/Toronto"  # Real timezone from database

        # Test Vancouver station - should return America/Vancouver (as configured in test data)
        response = await integration_client.get("/api/wind?stn=CYVR&hours=12")
        data = response.json()
        assert data["timezone"] == "America/Vancouver"  # Configured in test data

    @pytest.mark.anyio
    async def test_error_handling_integration(self, integration_client):
        """Test error handling across the stack."""
        # Test invalid station - should handle gracefully
        response = await integration_client.get("/api/wind?stn=INVALID")
        assert response.status_code == 200

        # Test invalid date format
        response = await integration_client.get("/day/invalid-date")
        assert response.status_code == 400

        # Test invalid time parameters - should return 422 for validation error
        response = await integration_client.get("/api/wind?hours=abc")
        assert response.status_code == 422  # Validation error

    @pytest.mark.anyio
    async def test_websocket_initial_data(
        self, ws_integration_client: AsyncClient, test_db_with_bulk_data
    ):
        """Test WebSocket integration."""

        check_latest_wind_obs = test_db_with_bulk_data.latest_wind_obs
        async with aconnect_ws("/ws/CYTZ", ws_integration_client) as websocket:
            # First message might be status update, then wind observation
            message = await websocket.receive_json()
            assert isinstance(message, dict)

            if message["type"] == "status_update":
                # If we got status update first, get the next message for wind observation
                message = await websocket.receive_json()
                assert isinstance(message, dict)

            assert message["type"] == "wind"
            latest_wind_obs = message["data"]
            # Should receive some JSON data structure
            update_time = datetime.fromtimestamp(latest_wind_obs["timestamp"], tz=UTC)
            assert update_time == check_latest_wind_obs["update_time"]
            assert latest_wind_obs["direction"] == check_latest_wind_obs["direction"]
            assert latest_wind_obs["speed_kts"] == check_latest_wind_obs["speed_kts"]
            assert latest_wind_obs["gust_kts"] == check_latest_wind_obs["gust_kts"]

    @pytest.mark.anyio
    async def test_websocket_live_update(
        self, ws_integration_client: AsyncClient, test_db_with_bulk_data
    ):
        """Test WebSocket integration."""

        check_latest_wind_obs = test_db_with_bulk_data.latest_wind_obs
        async with aconnect_ws("/ws/CYTZ", ws_integration_client) as websocket:
            # First message might be status update, then wind observation
            message = await websocket.receive_json()
            assert isinstance(message, dict)

            if message["type"] == "status_update":
                # If we got status update first, get the next message for wind observation
                message = await websocket.receive_json()
                assert isinstance(message, dict)

            assert message["type"] == "wind"
            latest_wind_obs = message["data"]
            # Should receive some JSON data structure
            update_time = datetime.fromtimestamp(latest_wind_obs["timestamp"], tz=UTC)
            assert update_time == check_latest_wind_obs["update_time"]
            assert latest_wind_obs["direction"] == check_latest_wind_obs["direction"]
            assert latest_wind_obs["speed_kts"] == check_latest_wind_obs["speed_kts"]
            assert latest_wind_obs["gust_kts"] == check_latest_wind_obs["gust_kts"]

            # Test live update
            await sleep(1)
            new_obs_time = datetime.now(UTC)
            await test_db_with_bulk_data.insert_new_wind_obs(
                station_name="CYTZ",
                direction=180,
                speed_kts=10,
                gust_kts=None,
                obs_time=new_obs_time,
            )
            updated_message = await websocket.receive_json()
            assert isinstance(updated_message, dict)
            assert updated_message["type"] == "wind"
            updated_wind_obs = updated_message["data"]
            assert updated_wind_obs["timestamp"] == new_obs_time.timestamp()
            assert updated_wind_obs["direction"] == 180
            assert updated_wind_obs["speed_kts"] == 10
            assert updated_wind_obs["gust_kts"] is None

    @pytest.mark.anyio
    async def test_performance_basic(self, integration_client_with_bulk_data):
        """Test basic performance: /api/wind?hours=24 responds in under 100 milliseconds."""
        from datetime import datetime

        start_time = datetime.now()
        response = await integration_client_with_bulk_data.get("/api/wind?hours=24")
        end_time = datetime.now()

        assert response.status_code == 200

        # Response should be reasonably fast
        response_time = (end_time - start_time).total_seconds()
        assert response_time < 0.1  # Basic performance check

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "app_with_bulk_data", [{"postgres_monitor_interval": 1.0}], indirect=True
    )
    async def test_listener_reconnection(
        self, ws_integration_client, test_db_with_bulk_data, app_with_bulk_data
    ):
        """The listener reconnects after the server drops its connection."""
        pg_manager = app_with_bulk_data.state.pg_manager
        check_latest_wind_obs = test_db_with_bulk_data.latest_wind_obs
        async with aconnect_ws("/ws/CYTZ", ws_integration_client) as websocket:
            # First message might be status update, then wind observation
            message = await websocket.receive_json()
            assert isinstance(message, dict)

            if message["type"] == "status_update":
                # If we got status update first, get the next message for wind observation
                message = await websocket.receive_json()
                assert isinstance(message, dict)

            assert message["type"] == "wind"
            latest_wind_obs = message["data"]
            # Should receive some JSON data structure
            update_time = datetime.fromtimestamp(latest_wind_obs["timestamp"], tz=UTC)
            assert update_time == check_latest_wind_obs["update_time"]
            assert latest_wind_obs["direction"] == check_latest_wind_obs["direction"]
            assert latest_wind_obs["speed_kts"] == check_latest_wind_obs["speed_kts"]
            assert latest_wind_obs["gust_kts"] == check_latest_wind_obs["gust_kts"]

            # Drop the listener's connection from the server side
            old_listener = pg_manager.pg_listener
            async with test_db_with_bulk_data.pool.acquire() as conn:
                assert await conn.fetchval(
                    "SELECT pg_terminate_backend($1)", old_listener.get_server_pid()
                )

            # Wait for the listener to reconnect
            for _ in range(50):
                await sleep(0.1)
                if (
                    pg_manager.pg_listener not in (None, old_listener)
                    and pg_manager.is_pg_listener_healthy
                ):
                    break
            else:
                pytest.fail("Postgres listener did not reconnect")

            # Test live updates continue
            new_obs_time = datetime.now(UTC)
            await test_db_with_bulk_data.insert_new_wind_obs(
                station_name="CYTZ",
                direction=180,
                speed_kts=10,
                gust_kts=None,
                obs_time=new_obs_time,
            )

            updated_message = await websocket.receive_json(timeout=1)
            assert isinstance(updated_message, dict)
            assert updated_message["type"] == "wind"
            updated_wind_obs = updated_message["data"]
            assert updated_wind_obs["timestamp"] == new_obs_time.timestamp()
            assert updated_wind_obs["direction"] == 180
            assert updated_wind_obs["speed_kts"] == 10
            assert updated_wind_obs["gust_kts"] is None


@pytest.mark.anyio
async def test_cache_hydration(test_db_with_bulk_data):
    """Startup hydrates the default station and recently scraped ones from the database,
    so the first live view request is a cache hit."""
    from httpx import ASGITransport

    from tests.conftest import running_app

    db = test_db_with_bulk_data
    await db.create_scraper_status("CYYZ", status="healthy", last_success_minutes_ago=5)
    await db.create_scraper_status(
        "CYVR", status="error", last_success_minutes_ago=3 * 24 * 60
    )

    async with running_app(db, cache_hydration_hours=24) as app:
        hydrator = app.state.cache_hydrator
        await hydrator.task
        assert hydrator.last_run["state"] == "done"
        stations = hydrator.last_run["stations"]
        assert stations[0] == "CYTZ"
        assert "CYYZ" in stations
        assert "CYVR" not in stations

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            for hours in (3, 24):
                response = await client.get(f"/api/wind?hours={hours}")
                assert response.status_code == 200
                data = response.json()
                assert data["cache_hit"]
                assert len(data["winddata"]) >= hours * 60 - 1
