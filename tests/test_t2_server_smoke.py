"""Real uvicorn server (real lifespan, real loopback socket) with the t2 profile.

Uses a disposable collection under tmp_path and an ephemeral loopback port. This is a
characterization test of the integrated startup path; it does not touch AnkiWeb.
"""

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from anki_connect_server.api import app
from anki_connect_server.config import get_config

TOKEN = "smoke-token-0123456789abcdef"


@pytest.fixture
def live_server(monkeypatch, tmp_path: Path) -> Iterator[tuple[str, Path]]:
    collection = tmp_path / "state" / "collection.anki2"
    collection.parent.mkdir()
    cfg = get_config()
    monkeypatch.setattr(cfg, "COLLECTION_PATH", str(collection))
    monkeypatch.setattr(cfg, "API_TOKEN", TOKEN)
    monkeypatch.setattr(cfg, "ALLOW_REQUEST_CREDENTIALS", False)
    monkeypatch.setattr(cfg, "ALLOW_SERVER_PATHS", False)
    monkeypatch.setattr(cfg, "REQUIRE_COLLECTION_PATH", True)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "server did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", collection
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_hardened_server_serves_only_authenticated_rpc_on_the_configured_collection(live_server):
    base, collection = live_server
    version = {"action": "version", "version": 6}

    assert httpx.get(f"{base}/health").json() == {"status": "healthy"}
    assert httpx.post(f"{base}/", json=version).status_code == 401
    assert httpx.post(f"{base}/api", json=version).status_code == 401
    assert (
        httpx.post(f"{base}/api", json=version, headers={"Authorization": "Bearer no"}).status_code
        == 401
    )

    ok = httpx.post(f"{base}/api", json=version, headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.json() == {"result": 6, "error": None}

    # The explicitly configured collection was created; no temp collection was used.
    assert collection.exists()
