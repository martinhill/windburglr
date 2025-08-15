import pytest
import subprocess
import time
import requests
import os
from contextlib import contextmanager


@contextmanager
def run_test_server():
    """Context manager to run the test server."""
    # Set test environment
    env = os.environ.copy()
    # Use a mock database URL to avoid real database dependency
    env["DATABASE_URL"] = "sqlite:///./test.db"  # Mock database
    env["PORT"] = "8001"  # Use different port for tests

    # Start server
    process = subprocess.Popen(
        [
            "python",
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8001",
            "--reload",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    for _ in range(30):  # Wait up to 30 seconds
        try:
            response = requests.get("http://localhost:8001/health", timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(1)
    else:
        process.terminate()
        process.wait()
        raise RuntimeError("Test server failed to start")

    try:
        yield "http://localhost:8001"
    finally:
        process.terminate()
        process.wait()


@pytest.fixture(scope="session")
def test_server_url():
    """Provide test server URL."""
    with run_test_server() as url:
        yield url
