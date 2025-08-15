#!/usr/bin/env python3
"""
Setup script for real PostgreSQL database testing.
"""

import os
import asyncio
import asyncpg
from datetime import datetime, timedelta


async def setup_real_database():
    """Setup the real database with proper schema and data."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        print("❌ TEST_DATABASE_URL not set")
        return False

    print("🔄 Setting up real PostgreSQL database...")

    try:
        conn = await asyncpg.connect(database_url)

        # Create extensions
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

        # Create station table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS station (
                id SERIAL PRIMARY KEY,
                name VARCHAR(10) UNIQUE NOT NULL,
                timezone VARCHAR(50) NOT NULL DEFAULT 'UTC'
            )
        """)

        # Create wind_obs table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wind_obs (
                station_id INTEGER REFERENCES station(id),
                update_time TIMESTAMP NOT NULL,
                direction NUMERIC,
                speed_kts NUMERIC,
                gust_kts NUMERIC
            )
        """)

        # Create hypertable
        try:
            await conn.execute(
                "SELECT create_hypertable('wind_obs', 'update_time', if_not_exists => TRUE)"
            )
        except Exception as e:
            print(f"⚠️  TimescaleDB hypertable: {e}")

        # Insert test stations
        stations = [
            ("CYTZ", "America/Toronto"),
            ("CYYZ", "America/Toronto"),
            ("CYVR", "America/Vancouver"),
        ]

        for name, timezone in stations:
            await conn.execute(
                """
                INSERT INTO station (name, timezone_name)
                VALUES ($1, $2)
                ON CONFLICT (name) DO UPDATE SET timezone_name = EXCLUDED.timezone_name
                """,
                name,
                timezone,
            )

        # Insert test wind data
        base_time = datetime.now()
        for station_name in ["CYTZ", "CYYZ", "CYVR"]:
            station_id = await conn.fetchval(
                "SELECT id FROM station WHERE name = $1", station_name
            )

            for i in range(24):  # 24 hours of data
                obs_time = base_time - timedelta(hours=i)
                await conn.execute(
                    """
                    INSERT INTO wind_obs (station_id, update_time, direction, speed_kts, gust_kts)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    station_id,
                    obs_time,
                    (i * 15) % 360,
                    5 + (i % 15),
                    7 + (i % 15),
                )

        await conn.close()
        print("✅ Real database setup completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(setup_real_database())
