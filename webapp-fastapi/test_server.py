#!/usr/bin/env python3
import requests
import subprocess
import time
import os
import signal


def test_server():
    env = os.environ.copy()
    env["PORT"] = "8001"
    env["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL")

    print("Starting test server...")
    p = subprocess.Popen(
        [
            "python",
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8001",
            "--log-level",
            "info",
        ],
        env=env,
    )

    time.sleep(5)

    try:
        print("Testing health endpoint...")
        response = requests.get("http://localhost:8001/health", timeout=10)
        print(f"Health check: {response.status_code}")
        print(f"Response: {response.json()}")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        p.send_signal(signal.SIGTERM)
        p.wait()
        print("Server stopped")


if __name__ == "__main__":
    test_server()
