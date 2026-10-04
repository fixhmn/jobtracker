import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def test_real_http_server(tmp_path):
    with socket.socket() as socket_:
        socket_.bind(("127.0.0.1", 0))
        port = socket_.getsockname()[1]
    key = secrets.token_urlsafe(32)
    environment = os.environ | {
        "API_KEY": key,
        "DATABASE_PATH": str(tmp_path / "runtime.db"),
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            for _ in range(100):
                assert process.poll() is None, "Uvicorn exited before startup"
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("API did not start within 10 seconds")
            assert client.get("/applications").status_code == 401
            client.headers["X-API-Key"] = key
            response = client.post(
                "/applications",
                json={
                    "company": "Runtime Demo",
                    "position": "Developer",
                    "url": "https://example.com/runtime",
                },
            )
            assert response.status_code == 201
            row_id = response.json()["id"]
            assert (
                client.patch(f"/applications/{row_id}", json={"status": "Applied"}).status_code
                == 200
            )
            assert client.get("/applications").json()["total"] == 1
            schema = client.get("/openapi.json").json()
            assert "/applications" in schema["paths"]
            assert client.get("/docs").status_code == 200
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
