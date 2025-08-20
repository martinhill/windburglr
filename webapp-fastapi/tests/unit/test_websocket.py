import pytest


def test_websocket_connection(test_client, mock_test_db_manager):
    """Test WebSocket connection establishment."""
    mock_test_db_manager.create_test_data()
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be established
        assert websocket is not None
        data = websocket.receive_json()
        assert isinstance(data["timestamp"], float)
        assert isinstance(data["direction"], int)
        assert isinstance(data["speed_kts"], int)
        assert isinstance(data["gust_kts"], int)
        assert 0 <= data["direction"] <= 360


def test_websocket_different_stations(test_client, mock_test_db_manager):
    """Test WebSocket connections to different stations."""
    mock_test_db_manager.create_test_data("CYTZ")
    mock_test_db_manager.create_test_data("CYYZ")
    with (
        test_client.websocket_connect("/ws/CYTZ") as ws1,
        test_client.websocket_connect("/ws/CYYZ") as ws2,
    ):
        # Both connections should be active
        assert ws1 is not None
        assert ws2 is not None

        data1 = ws1.receive_json()
        assert isinstance(data1["timestamp"], float)
        assert isinstance(data1["direction"], int)
        assert isinstance(data1["speed_kts"], int)
        assert isinstance(data1["gust_kts"], int)
        assert 0 <= data1["direction"] <= 360

        data2 = ws2.receive_json()
        assert isinstance(data2["timestamp"], float)
        assert isinstance(data2["direction"], int)
        assert isinstance(data2["speed_kts"], int)
        assert isinstance(data2["gust_kts"], int)
        assert 0 <= data2["direction"] <= 360


def test_websocket_ping_pong(test_client):
    """Test websocket ping"""
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # With no wind data, there is no latest wind observation
        # Check for ping
        websocket.send_json({"type": "ping"})
        ping_response = websocket.receive_json()
        print(ping_response)
        assert ping_response["type"] == "pong"

@pytest.mark.slow
def test_websocket_ping(test_client):
    """Test websocket ping"""
    # Check for ping
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Check for ping
        server_ping = websocket.receive_json()
        assert server_ping["type"] == "ping"
