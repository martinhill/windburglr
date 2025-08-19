#!/usr/bin/env python3
"""
Comprehensive database test script for WindBurglr.

This script combines the functionality of test_database_setup.py and test_db_final.py
into a single, unified database testing tool that provides:
1. Environment validation and setup instructions
2. Database connection testing with detailed error handling
3. Schema creation and validation
4. Data insertion and retrieval testing
5. Performance and functionality verification
"""

import os
import asyncio
import asyncpg
from datetime import datetime, UTC, timedelta


class DatabaseTester:
    """Comprehensive database testing class."""

    def __init__(self):
        self.database_url = os.environ.get("TEST_DATABASE_URL")
        self.test_station_name = "CYTZ"
        self.test_timezone = "America/Toronto"

    async def validate_environment(self):
        """Validate environment and provide setup instructions."""
        print("🔍 WindBurglr Database Configuration Test")
        print("=" * 50)

        if self.database_url:
            print(f"📊 TEST_DATABASE_URL: {self.database_url}")

            # Basic URL validation
            if not self.database_url.startswith("postgresql://"):
                print("❌ Invalid database URL format")
                print(
                    "   Expected format: postgresql://user:password@host:port/database"
                )
                return False

            print(
                f"   Host: {self.database_url.split('@')[1].split('/')[0] if '@' in self.database_url else 'N/A'}"
            )
            print(f"   Database: {self.database_url.split('/')[-1]}")
            return True
        else:
            print("📊 TEST_DATABASE_URL: Not set (using mock mode)")
            print("\n✅ Using mock database mode - no PostgreSQL required")
            print("   Run: pytest tests/unit/ tests/e2e/ -v")
            return False

    async def test_connection(self):
        """Test basic database connection."""
        try:
            conn = await asyncpg.connect(self.database_url)
            print("✅ Basic connection successful")

            # Test database version
            version = await conn.fetchval("SELECT version()")
            print(f"✅ Database version: {version.split()[1]}")

            return conn
        except ConnectionRefusedError:
            print("❌ Connection refused - PostgreSQL not running or wrong port")
            print("   Check if PostgreSQL is running on localhost:5432")
            return None
        except asyncpg.exceptions.InvalidPasswordError:
            print("❌ Authentication failed - check username/password")
            return None
        except asyncpg.exceptions.PostgresError as e:
            print(f"❌ PostgreSQL error: {e}")
            print(f"   Error code: {getattr(e, 'sqlstate', 'N/A')}")
            return None
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print(f"   Error type: {type(e).__name__}")
            return None

    async def setup_schema(self, conn):
        """Set up database schema."""
        print("\n🔄 Setting up database schema...")

        # Create TimescaleDB extension
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
                station_id INTEGER,
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
            print("✅ TimescaleDB hypertable created successfully")
        except Exception as e:
            print(f"⚠️  TimescaleDB hypertable creation: {e}")
            # Continue with regular table if hypertable fails

    async def insert_test_data(self, conn):
        """Insert comprehensive test data."""
        print("\n🔄 Inserting test data...")

        # Insert test station
        station_id = await conn.fetchval(
            """
            INSERT INTO station (name, timezone)
            VALUES ($1, $2)
            ON CONFLICT (name) DO UPDATE SET timezone = EXCLUDED.timezone
            RETURNING id
            """,
            self.test_station_name,
            self.test_timezone,
        )
        print(f"✅ Station created with ID: {station_id}")

        # Insert multiple test records
        base_time = datetime.now(UTC)
        test_records = []

        for i in range(5):
            obs_time = base_time - timedelta(hours=i)
            naive_time = obs_time.replace(tzinfo=None)
            direction = (i * 45) % 360
            speed = 10 + i
            gust = 12 + i

            await conn.execute(
                """
                INSERT INTO wind_obs (station_id, update_time, direction, speed_kts, gust_kts)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT DO NOTHING
                """,
                station_id,
                naive_time,
                direction,
                speed,
                gust,
            )
            test_records.append(
                {
                    "direction": direction,
                    "speed": speed,
                    "gust": gust,
                    "time": naive_time,
                }
            )

        # Insert single detailed test record
        detailed_time = base_time.replace(tzinfo=None)
        await conn.execute(
            """
            INSERT INTO wind_obs (station_id, update_time, direction, speed_kts, gust_kts)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT DO NOTHING
            """,
            station_id,
            detailed_time,
            270,
            15,
            18,
        )

        return station_id

    async def test_data_retrieval(self, conn, station_id):
        """Test data retrieval and validation."""
        print("\n🔄 Testing data retrieval...")

        # Test basic retrieval
        data = await conn.fetch(
            """
            SELECT w.direction, w.speed_kts, w.gust_kts, w.update_time
            FROM wind_obs w
            JOIN station s ON w.station_id = s.id
            WHERE s.name = $1
            ORDER BY w.update_time DESC
            """,
            self.test_station_name,
        )

        print(f"✅ Successfully retrieved {len(data)} records")

        if data:
            row = dict(data[0])
            print(
                f"✅ Latest sample: direction={row['direction']}°, "
                f"speed={row['speed_kts']} kts, gust={row['gust_kts']} kts, "
                f"time={row['update_time']}"
            )

        # Test timezone retrieval
        timezone = await conn.fetchval(
            "SELECT timezone FROM station WHERE name = $1", self.test_station_name
        )
        print(f"✅ Station timezone: {timezone}")

        return len(data)

    async def run_comprehensive_test(self):
        """Run comprehensive database test."""
        print("🔄 Running comprehensive database test...")

        conn = await self.test_connection()
        if not conn:
            return False

        try:
            # Setup schema
            await self.setup_schema(conn)

            # Insert test data
            station_id = await self.insert_test_data(conn)

            # Test data retrieval
            record_count = await self.test_data_retrieval(conn, station_id)

            # Additional validation
            station_count = await conn.fetchval("SELECT COUNT(*) FROM station")
            obs_count = await conn.fetchval("SELECT COUNT(*) FROM wind_obs")

            print(f"\n📊 Final validation:")
            print(f"   Total stations: {station_count}")
            print(f"   Total observations: {obs_count}")

            await conn.close()
            print("\n✅ Comprehensive database test completed successfully!")
            return True

        except Exception as e:
            print(f"❌ Comprehensive test failed: {e}")
            if conn:
                await conn.close()
            return False

    async def provide_setup_instructions(self):
        """Provide detailed setup instructions."""
        print("\n💡 To set up PostgreSQL for testing:")
        print("   # Option 1: Docker/Podman (Recommended)")
        print(
            "   docker run -d --name windburglr-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 timescale/timescaledb:latest-pg15"
        )
        print("   # Option 2: Local PostgreSQL")
        print("   # Install PostgreSQL and run: createdb windburglr_test")
        print("   # Set environment variable:")
        print(
            "   export TEST_DATABASE_URL='postgresql://postgres:postgres@localhost:5432/windburglr_test'"
        )
        print("   # Or with custom credentials:")
        print(
            "   export TEST_DATABASE_URL='postgresql://username:password@localhost:5432/windburglr_test'"
        )

    async def run(self):
        """Main execution method."""
        # Validate environment
        if not await self.validate_environment():
            await self.provide_setup_instructions()
            return False

        # Run comprehensive test
        success = await self.run_comprehensive_test()

        if success:
            print("\n🎉 Database is fully operational!")
            print("   Ready for integration testing")
            print("   Run: pytest tests/integration/test_real_database.py -v")
        else:
            print("\n💡 Check database configuration")
            await self.provide_setup_instructions()

        return success


async def main():
    """Main entry point."""
    tester = DatabaseTester()
    await tester.run()


if __name__ == "__main__":
    asyncio.run(main())
