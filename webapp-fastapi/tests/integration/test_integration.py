import pytest
from httpx_ws import aconnect_ws


class TestIntegration:
    """Integration tests combining multiple components with sync fixtures."""

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
    async def test_timezone_handling(self, integration_client):
        """Test timezone handling across different stations."""
        # Test Toronto station - should return America/Toronto with real database
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
    async def test_websocket(self, integration_client, test_db_manager):
        """Test WebSocket integration."""
        pytest.skip("WebSocket test needs implementation")
        await test_db_manager.create_test_data(station_name="CYTZ", days=1)
        async with aconnect_ws("http://testserver/ws/CYTZ", integration_client) as websocket:
            data = await websocket.receive_json()
            assert isinstance(data, dict)
            # Should receive some JSON data structure
            assert len(data) > 0

    @pytest.mark.anyio
    async def test_performance_basic(self, integration_client, test_db_manager):
        """Test basic performance."""
        from datetime import datetime

        await test_db_manager.create_test_data(station_name="CYTZ", days=7)

        start_time = datetime.now()
        response = await integration_client.get("/api/wind?hours=24")
        end_time = datetime.now()

        assert response.status_code == 200

        # Response should be reasonably fast
        response_time = (end_time - start_time).total_seconds()
        assert response_time < 0.2  # Basic performance check
