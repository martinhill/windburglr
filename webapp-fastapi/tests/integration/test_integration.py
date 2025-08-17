import pytest


class TestIntegration:
    """Integration tests combining multiple components with sync fixtures."""

    @pytest.mark.anyio
    async def test_full_data_flow(self, integration_client):
        """Test complete data flow from API to frontend."""
        response = await integration_client.get("/api/wind?hours=24")
        assert response.status_code == 200

        data = response.json()
        assert "station" in data
        assert "winddata" in data
        assert "timezone" in data
        assert "start_time" in data
        assert "end_time" in data
        assert data["station"] == "CYTZ"

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
    async def test_webbsocket_integration(self, integration_client):
        """Test WebSocket integration."""
        # Skip WebSocket test for HTTP client - this requires a different testing approach
        pytest.skip(
            "WebSocket testing requires specialized client - tested in unit tests"
        )

    @pytest.mark.anyio
    async def test_performance_basic(self, integration_client):
        """Test basic performance."""
        from datetime import datetime

        start_time = datetime.now()
        response = await integration_client.get("/api/wind?hours=24")
        end_time = datetime.now()

        assert response.status_code == 200

        # Response should be reasonably fast
        response_time = (end_time - start_time).total_seconds()
        assert response_time < 2.0  # Basic performance check
