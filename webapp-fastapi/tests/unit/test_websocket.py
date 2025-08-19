def test_websocket_connection(test_client, mock_test_db_manager):
    """Test WebSocket connection establishment."""
    test_data = mock_test_db_manager.create_test_data()
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be established
        assert websocket is not None
        data = websocket.receive_json()
        assert isinstance(data["timestamp"], float)
        assert isinstance(data["direction"], int)
        assert isinstance(data["speed_kts"], int)
        assert isinstance(data["gust_kts"], int)
        assert 0 <= data["direction"] <= 360


def test_websocket_different_stations(test_client):
    """Test WebSocket connections to different stations."""
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


def test_websocket_disconnect(test_client):
    """Test WebSocket disconnection."""
    with test_client.websocket_connect("/ws/CYTZ") as websocket:
        # Connection should be active
        assert websocket is not None
