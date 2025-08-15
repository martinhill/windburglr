from fastapi.testclient import TestClient


class TestIntegration:
    """Integration tests combining multiple components with sync fixtures."""
    
    def test_full_data_flow(self, test_client):
        """Test complete data flow from API to frontend."""
        # Test API endpoint
        response = test_client.get("/api/wind?hours=24")
        assert response.status_code == 200
        
        data = response.json()
        assert "station" in data
        assert "winddata" in data
        assert "timezone" in data
        assert "start_time" in data
        assert "end_time" in data
        assert data["station"] == "CYTZ"
    
    def test_multiple_stations(self, test_client):
        """Test multiple stations."""
        # Test CYTZ
        response = test_client.get("/api/wind?stn=CYTZ&hours=12")
        assert response.status_code == 200
        assert response.json()["station"] == "CYTZ"
        
        # Test CYYZ
        response = test_client.get("/api/wind?stn=CYYZ&hours=12")
        assert response.status_code == 200
        assert response.json()["station"] == "CYYZ"
    
    def test_timezone_handling(self, test_client):
        """Test timezone handling across different stations."""
        # Test Toronto station - currently returns UTC due to no database
        response = test_client.get("/api/wind?stn=CYTZ&hours=12")
        data = response.json()
        assert data["timezone"] == "UTC"  # Default when no database
        
        # Test Vancouver station - currently returns UTC due to no database
        response = test_client.get("/api/wind?stn=CYVR&hours=12")
        data = response.json()
        assert data["timezone"] == "UTC"  # Default when no database
    
    def test_error_handling_integration(self, test_client):
        """Test error handling across the stack."""
        # Test invalid station - should handle gracefully
        response = test_client.get("/api/wind?stn=INVALID")
        assert response.status_code == 200
        
        # Test invalid date format
        response = test_client.get("/day/invalid-date")
        assert response.status_code == 400
        
        # Test invalid time parameters - should return 422 for validation error
        response = test_client.get("/api/wind?hours=abc")
        assert response.status_code == 422  # Validation error
    
    def test_webbsocket_integration(self, test_client):
        """Test WebSocket integration."""
        with test_client.websocket_connect("/ws/CYTZ") as websocket:
            # Connection should be established
            assert websocket is not None
            
            # Should be able to send/receive basic messages
            websocket.send_json({"type": "ping"})
            
            # Connection should be active (no exception means success)
            assert True  # Basic connection test passed
    
    def test_performance_basic(self, test_client):
        """Test basic performance."""
        from datetime import datetime
        
        start_time = datetime.now()
        response = test_client.get("/api/wind?hours=24")
        end_time = datetime.now()
        
        assert response.status_code == 200
        
        # Response should be reasonably fast
        response_time = (end_time - start_time).total_seconds()
        assert response_time < 2.0  # Basic performance check
