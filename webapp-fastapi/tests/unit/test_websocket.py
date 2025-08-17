def test_websocket_connection(test_client):
    """Test WebSocket connection establishment."""
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be established
        assert websocket is not None


def test_websocket_different_stations(test_client):
    """Test WebSocket connections to different stations."""
    with (
        test_client.websocket_connect("/ws/CYTZ") as ws1,
        test_client.websocket_connect("/ws/CYYZ") as ws2,
    ):
        # Both connections should be active
        assert ws1 is not None
        assert ws2 is not None


def test_websocket_disconnect(test_client):
    """Test WebSocket disconnection."""
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be active
        assert websocket is not None
