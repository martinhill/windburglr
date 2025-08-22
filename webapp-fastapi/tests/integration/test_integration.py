import pytest
from asyncio import sleep
from datetime import datetime, timezone
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
    async def test_timezone_handling(self, integration_client, test_db_manager, sample_stations):
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
        self,
        ws_integration_client: AsyncClient,
        test_db_with_bulk_data):
        """Test WebSocket integration."""

        check_latest_wind_obs = test_db_with_bulk_data.latest_wind_obs
        async with aconnect_ws("/ws/CYTZ", ws_integration_client) as websocket:
            #  The first message should be the latest wind observation
            latest_wind_obs = await websocket.receive_json()
            assert isinstance(latest_wind_obs, dict)
            # Should receive some JSON data structure
            update_time = datetime.fromtimestamp(latest_wind_obs["timestamp"], tz=timezone.utc).replace(tzinfo=None)
            assert update_time == check_latest_wind_obs["update_time"]
            assert latest_wind_obs["direction"] == check_latest_wind_obs["direction"]
            assert latest_wind_obs["speed_kts"] == check_latest_wind_obs["speed_kts"]
            assert latest_wind_obs["gust_kts"] == check_latest_wind_obs["gust_kts"]

    @pytest.mark.anyio
    async def test_websocket_live_update(self, ws_integration_client: AsyncClient, test_db_with_bulk_data):
        """Test WebSocket integration."""

        check_latest_wind_obs = test_db_with_bulk_data.latest_wind_obs
        async with aconnect_ws("/ws/CYTZ", ws_integration_client) as websocket:
            #  The first message should be the latest wind observation
            latest_wind_obs = await websocket.receive_json()
            assert isinstance(latest_wind_obs, dict)
            # Should receive some JSON data structure
            update_time = datetime.fromtimestamp(latest_wind_obs["timestamp"], tz=timezone.utc).replace(tzinfo=None)
            assert update_time == check_latest_wind_obs["update_time"]
            assert latest_wind_obs["direction"] == check_latest_wind_obs["direction"]
            assert latest_wind_obs["speed_kts"] == check_latest_wind_obs["speed_kts"]
            assert latest_wind_obs["gust_kts"] == check_latest_wind_obs["gust_kts"]

            # Test live update
            await sleep(1)
            new_obs_time = datetime.now(timezone.utc)
            await test_db_with_bulk_data.insert_new_wind_obs(
                station_name="CYTZ",
                direction=180,
                speed_kts=10,
                gust_kts=None,
                obs_time=new_obs_time.replace(tzinfo=None))
            updated_wind_obs = await websocket.receive_json()
            assert isinstance(updated_wind_obs, dict)
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

    @pytest.mark.slow
    @pytest.mark.anyio
    async def test_listener_reconnection(
        self, ws_integration_client, test_db_with_bulk_data, persistent_connection):
        """Test listener reconnection."""
        check_latest_wind_obs = test_db_with_bulk_data.latest_wind_obs
        async with aconnect_ws("/ws/CYTZ", ws_integration_client) as websocket:
            #  The first message should be the latest wind observation
            latest_wind_obs = await websocket.receive_json()
            assert isinstance(latest_wind_obs, dict)
            # Should receive some JSON data structure
            update_time = datetime.fromtimestamp(latest_wind_obs["timestamp"], tz=timezone.utc).replace(tzinfo=None)
            assert update_time == check_latest_wind_obs["update_time"]
            assert latest_wind_obs["direction"] == check_latest_wind_obs["direction"]
            assert latest_wind_obs["speed_kts"] == check_latest_wind_obs["speed_kts"]
            assert latest_wind_obs["gust_kts"] == check_latest_wind_obs["gust_kts"]

            # Close the listener Connection
            await persistent_connection.close()

            # Ensure enough time has passed for the listener to reconnect
            await sleep(35)
            # Ignore the ping message
            ping = await websocket.receive_json()
            assert ping["type"] == "ping"

            # Test live updates continue
            new_obs_time = datetime.now(timezone.utc)
            await test_db_with_bulk_data.insert_new_wind_obs(
                station_name="CYTZ",
                direction=180,
                speed_kts=10,
                gust_kts=None,
                obs_time=new_obs_time.replace(tzinfo=None))

            updated_wind_obs = await websocket.receive_json()
            assert isinstance(updated_wind_obs, dict)
            assert updated_wind_obs["timestamp"] == new_obs_time.timestamp()
            assert updated_wind_obs["direction"] == 180
            assert updated_wind_obs["speed_kts"] == 10
            assert updated_wind_obs["gust_kts"] is None
