import os
import socket
import subprocess
import time
from contextlib import contextmanager

import pytest
import requests


def get_free_port():
    """Get a free port for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


@contextmanager
def run_test_server():
    """Context manager to run the test server."""
    port = get_free_port()

    # Set test environment
    env = os.environ.copy()
    env["DATABASE_URL"] = env["TEST_DATABASE_URL"]
    env["PORT"] = str(port)

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
            str(port),
        ],  # Remove --reload for tests (faster startup)
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = f"http://localhost:{port}"

    # Wait for server to start with better error reporting
    last_error = None
    for i in range(30):
        try:
            response = requests.get(f"{url}/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep(1)
    else:
        # Capture any error output
        stdout, stderr = process.communicate(timeout=5)
        process.terminate()
        process.wait()
        raise RuntimeError(
            f"Test server failed to start after 30 seconds. "
            f"Last error: {last_error}. "
            f"Server output: {stderr.decode() if stderr else 'No stderr'}"
        )

    try:
        yield url
    finally:
        process.terminate()
        process.wait()


@pytest.fixture(scope="session")
def test_server_url():
    """Provide test server URL."""
    with run_test_server() as url:
        yield url
