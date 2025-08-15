from datetime import datetime, timedelta, UTC
from typing import List, Dict, Any
import pytest

class WindDataGenerator:
    """Generate realistic test wind data."""

    @staticmethod
    def generate_hourly_data(
        station: str = "CYTZ",
        hours: int = 24,
        base_direction: int = 270,
        base_speed: int = 10,
        gust_variance: int = 5
    ) -> List[Dict[str, Any]]:
        """Generate hourly wind data."""
        data = []
        now = datetime.now(UTC)

        for i in range(hours):
            timestamp = now - timedelta(hours=i)

            # Add some realistic variation
            direction = base_direction + (i % 30) - 15  # ±15° variation
            speed = base_speed + (i % 8) - 4  # ±4 kts variation
            gust = speed + (i % gust_variance) + 2  # Gust 2-7 kts above speed

            data.append({
                "station": station,
                "direction": direction % 360,
                "speed_kts": max(0, speed),
                "gust_kts": max(0, gust),
                "update_time": timestamp
            })

        return data

    @staticmethod
    def generate_storm_data(
        station: str = "CYTZ",
        duration_hours: int = 6,
        max_speed: int = 45
    ) -> List[Dict[str, Any]]:
        """Generate storm condition data."""
        data = []
        now = datetime.now(UTC)

        for i in range(duration_hours):
            timestamp = now - timedelta(hours=i)

            # Build up to storm
            if i < 2:
                speed = 15 + (i * 5)
            elif i < 4:
                speed = 25 + (i * 3)
            else:
                speed = max_speed - (i * 2)

            gust = speed + 10
            direction = 180 + (i * 20)  # Shifting winds

            data.append({
                "station": station,
                "direction": direction % 360,
                "speed_kts": speed,
                "gust_kts": gust,
                "update_time": timestamp
            })

        return data

    @staticmethod
    def generate_calm_data(
        station: str = "CYTZ",
        duration_hours: int = 12
    ) -> List[Dict[str, Any]]:
        """Generate calm wind conditions."""
        data = []
        now = datetime.now(UTC)

        for i in range(duration_hours):
            timestamp = now - timedelta(hours=i)

            # Very light winds
            speed = 2 + (i % 3)  # 2-4 kts
            gust = speed + 1
            direction = 0  # Variable/Calm

            data.append({
                "station": station,
                "direction": direction,
                "speed_kts": speed,
                "gust_kts": gust,
                "update_time": timestamp
            })

        return data

@pytest.fixture
def wind_data_generator():
    """Provide wind data generator."""
    return WindDataGenerator()
