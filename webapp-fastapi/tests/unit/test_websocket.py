from fastapi.testclient import TestClient


def test_websocket_connection():
    """Test WebSocket connection establishment."""
    from main import app

    client = TestClient(app)

    with client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be established
        assert websocket is not None


def test_websocket_different_stations():
    """Test WebSocket connections to different stations."""
    from main import app

    client = TestClient(app)

    with (
        client.websocket_connect("/ws/CYTZ") as ws1,
        client.websocket_connect("/ws/CYYZ") as ws2,
    ):
        # Both connections should be active
        assert ws1 is not None
        assert ws2 is not None


def test_websocket_disconnect():
    """Test WebSocket disconnection."""
    from main import app

    client = TestClient(app)

    with client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be active
        assert websocket is not None
