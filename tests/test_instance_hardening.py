"""Instance-hardening behaviour: optional bearer token on the RPC routes.

Every test uses the shared disposable-collection ``anki_wrapper`` fixture; none
touch a real collection or the network.
"""

import base64
import hmac
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from anki_connect_server.api import app
from anki_connect_server.config import get_config

TOKEN = "t2-test-token-0123456789abcdef"
VERSION_REQUEST = {"action": "version", "version": 6}


@pytest.fixture
def served_wrapper(anki_wrapper):
    app.state.anki_wrapper = anki_wrapper
    yield anki_wrapper
    app.state.anki_wrapper = None


@pytest.fixture
def token_required(monkeypatch):
    monkeypatch.setattr(get_config(), "API_TOKEN", TOKEN)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/api"])
async def test_legacy_default_has_no_wire_authentication(served_wrapper, path):
    async with _client() as client:
        response = await client.post(path, json=VERSION_REQUEST)
    assert response.status_code == 200
    assert response.json() == {"result": 6, "error": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/api"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer"},
        {"Authorization": f"Bearer {TOKEN} "},
        {"Authorization": f"Bearer  {TOKEN}"},
        {"Authorization": TOKEN},
        {"X-Api-Token": TOKEN},
    ],
)
async def test_missing_or_wrong_token_is_401(served_wrapper, token_required, path, headers):
    async with _client() as client:
        response = await client.post(path, json=VERSION_REQUEST, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"result": None, "error": "Unauthorized"}
    assert TOKEN not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/api"])
@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
async def test_correct_token_is_accepted(served_wrapper, token_required, path, scheme):
    async with _client() as client:
        response = await client.post(
            path, json=VERSION_REQUEST, headers={"Authorization": f"{scheme} {TOKEN}"}
        )
    assert response.status_code == 200
    assert response.json() == {"result": 6, "error": None}


@pytest.mark.asyncio
async def test_health_stays_open_when_token_is_required(served_wrapper, token_required):
    async with _client() as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_auth_runs_before_body_parsing(served_wrapper, token_required):
    """An unauthenticated caller must get 401, never a 422 that reveals the schema."""
    async with _client() as client:
        garbage = await client.post(
            "/", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        wrong_shape = await client.post("/api", json={"nope": 1})
    assert garbage.status_code == 401
    assert wrong_shape.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc", "/unknown", "/api/"])
async def test_every_other_route_requires_the_token(served_wrapper, token_required, path):
    async with _client() as client:
        response = await client.get(path)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_ascii_authorization_header_is_401_not_500(served_wrapper, token_required):
    async with _client() as client:
        response = await client.post(
            "/", json=VERSION_REQUEST, headers=[(b"authorization", b"Bearer \xe9\xff")]
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_comparison_is_constant_time(served_wrapper, token_required, monkeypatch):
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    async with _client() as client:
        await client.post("/", json=VERSION_REQUEST, headers={"Authorization": "Bearer nope"})
        await client.post("/", json=VERSION_REQUEST, headers={"Authorization": f"Bearer {TOKEN}"})
    assert len(calls) == 2
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls)


@pytest.mark.asyncio
async def test_token_is_never_logged(served_wrapper, token_required, caplog):
    caplog.set_level(logging.DEBUG)
    async with _client() as client:
        await client.post(
            "/", json=VERSION_REQUEST, headers={"Authorization": "Bearer leaked-guess"}
        )
        await client.post("/", json=VERSION_REQUEST, headers={"Authorization": f"Bearer {TOKEN}"})
    assert TOKEN not in caplog.text
    assert "leaked-guess" not in caplog.text


# ---------------------------------------------------------------------------
# ALLOW_REQUEST_CREDENTIALS=false: username/password/endpoint overrides refused
# ---------------------------------------------------------------------------

SYNC_ACTIONS = ["sync", "syncStatus", "syncMedia"]
CREDENTIAL_OVERRIDES = [
    {"username": "attacker@example.com"},
    {"password": "attacker-pw-123"},
    {"endpoint": "https://sync.attacker.example/"},
    {"username": "", "password": "", "endpoint": ""},
    {"username": "u", "password": "p", "endpoint": "https://sync.attacker.example/"},
]


@pytest.fixture
def credentials_forbidden(monkeypatch):
    monkeypatch.setattr(get_config(), "ALLOW_REQUEST_CREDENTIALS", False)


@pytest.fixture
def no_network_sync(served_wrapper):
    """Any attempt to log in to or sync with AnkiWeb fails the test loudly."""
    col = served_wrapper.col
    boom = AssertionError("sync backend must not be reached")
    with (
        patch.object(col, "sync_login", side_effect=boom) as login,
        patch.object(col, "sync_collection", side_effect=boom),
        patch.object(col, "sync_media", side_effect=boom),
        patch.object(col, "sync_status", side_effect=boom),
    ):
        yield login


async def _rpc(payload: dict[str, Any]) -> dict[str, Any]:
    async with _client() as client:
        response = await client.post("/api", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", SYNC_ACTIONS)
@pytest.mark.parametrize("override", CREDENTIAL_OVERRIDES)
async def test_credential_overrides_are_refused_for_every_sync_variant(
    credentials_forbidden, no_network_sync, action, override
):
    body = await _rpc({"action": action, "version": 6, "params": override})
    assert body["result"] is None
    assert "ANKICONNECT_ALLOW_REQUEST_CREDENTIALS" in body["error"]
    assert "attacker-pw-123" not in str(body)
    no_network_sync.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", SYNC_ACTIONS)
async def test_credential_override_refused_inside_multi(
    credentials_forbidden, no_network_sync, action
):
    body = await _rpc(
        {
            "action": "multi",
            "version": 6,
            "params": {
                "actions": [
                    {"action": action, "params": {"username": "x", "password": "y"}},
                    {"action": "version"},
                ]
            },
        }
    )
    refused, ok = body["result"]
    assert "ANKICONNECT_ALLOW_REQUEST_CREDENTIALS" in refused["error"]
    assert ok == 6
    no_network_sync.assert_not_called()


@pytest.mark.asyncio
async def test_credential_override_refused_inside_nested_multi(
    credentials_forbidden, no_network_sync
):
    inner = {
        "action": "multi",
        "params": {"actions": [{"action": "syncMedia", "params": {"endpoint": "https://e/"}}]},
    }
    body = await _rpc(
        {"action": "multi", "version": 6, "params": {"actions": [inner, {"action": "version"}]}}
    )
    (nested,), ok = body["result"]
    assert "ANKICONNECT_ALLOW_REQUEST_CREDENTIALS" in nested["error"]
    assert ok == 6
    no_network_sync.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "needle"),
    [("sync", "required for sync"), ("syncStatus", "required for sync status")],
)
async def test_sync_without_overrides_still_uses_configured_credentials(
    credentials_forbidden, served_wrapper, monkeypatch, action, needle
):
    """The flag only forbids request overrides; the env-configured account is
    still what a hardened instance syncs with (here: none configured)."""
    monkeypatch.setattr(get_config(), "ANKIWEB_USER", None)
    monkeypatch.setattr(get_config(), "ANKIWEB_PASS", None)
    body = await _rpc({"action": action, "version": 6, "params": {"username": None}})
    assert needle in body["error"]
    assert "ALLOW_REQUEST_CREDENTIALS" not in body["error"]


def test_legacy_default_still_honours_request_credentials(anki_wrapper):
    with (
        patch.object(anki_wrapper.col, "sync_login", return_value=Mock()) as login,
        patch.object(anki_wrapper.col, "sync_status", return_value=Mock(required=0)),
    ):
        anki_wrapper.sync_status(username="u", password="p", endpoint="https://sync.example/")
    login.assert_called_once_with(username="u", password="p", endpoint="https://sync.example/")


# ---------------------------------------------------------------------------
# ALLOW_SERVER_PATHS=false: no server-side file or URL access via the RPC
# ---------------------------------------------------------------------------

PATHS_FLAG = "ANKICONNECT_ALLOW_SERVER_PATHS"


@pytest.fixture
def server_paths_forbidden(monkeypatch):
    monkeypatch.setattr(get_config(), "ALLOW_SERVER_PATHS", False)


@pytest.fixture
def host_secret(tmp_path):
    """A readable file outside the media dir, standing in for e.g. /etc/passwd."""
    secret = tmp_path / "host-secret.txt"
    secret.write_text("TOP-SECRET-HOST-CONTENT")
    return secret


def _media_file(wrapper, name: str):
    return Path(wrapper.get_media_dir_path()) / name


@pytest.mark.asyncio
async def test_store_media_file_path_is_refused_and_nothing_is_read(
    server_paths_forbidden, served_wrapper, host_secret
):
    body = await _rpc(
        {
            "action": "storeMediaFile",
            "version": 6,
            "params": {"filename": "loot.txt", "path": str(host_secret)},
        }
    )
    assert body["result"] is None
    assert PATHS_FLAG in body["error"]
    assert "TOP-SECRET-HOST-CONTENT" not in str(body)
    assert not _media_file(served_wrapper, "loot.txt").exists()


@pytest.mark.asyncio
async def test_store_media_file_path_is_not_silently_ignored_when_data_is_present(
    server_paths_forbidden, served_wrapper, host_secret
):
    body = await _rpc(
        {
            "action": "storeMediaFile",
            "version": 6,
            "params": {
                "filename": "ok.txt",
                "data": base64.b64encode(b"hello").decode(),
                "path": str(host_secret),
            },
        }
    )
    assert PATHS_FLAG in body["error"]
    assert not _media_file(served_wrapper, "ok.txt").exists()


@pytest.mark.asyncio
async def test_store_media_file_url_is_refused_without_any_outbound_request(
    server_paths_forbidden, served_wrapper, httpserver
):
    httpserver.expect_request("/pic.png").respond_with_data(b"png-bytes")
    body = await _rpc(
        {
            "action": "storeMediaFile",
            "version": 6,
            "params": {"filename": "pic.png", "url": httpserver.url_for("/pic.png")},
        }
    )
    assert PATHS_FLAG in body["error"]
    assert httpserver.log == []
    assert not _media_file(served_wrapper, "pic.png").exists()


@pytest.mark.asyncio
async def test_store_media_file_base64_data_still_works_when_paths_are_forbidden(
    server_paths_forbidden, served_wrapper
):
    body = await _rpc(
        {
            "action": "storeMediaFile",
            "version": 6,
            "params": {"filename": "plain.txt", "data": base64.b64encode(b"hello").decode()},
        }
    )
    assert body == {"result": None, "error": None}
    assert _media_file(served_wrapper, "plain.txt").read_bytes() == b"hello"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("importPackage", {"path": "/etc/hostname"}),
        ("importPackage", {}),
        ("exportPackage", {"deck": "Default", "path": "EXPORT_TARGET"}),
        ("exportPackage", {}),
    ],
)
async def test_package_import_and_export_are_refused(
    server_paths_forbidden, served_wrapper, tmp_path, action, params
):
    params = {
        k: (str(tmp_path / "out.apkg") if v == "EXPORT_TARGET" else v) for k, v in params.items()
    }
    body = await _rpc({"action": action, "version": 6, "params": params})
    assert body["result"] is None
    assert PATHS_FLAG in body["error"]
    assert not (tmp_path / "out.apkg").exists()


@pytest.mark.asyncio
async def test_server_path_actions_are_refused_inside_multi_and_nested_multi(
    server_paths_forbidden, served_wrapper, host_secret, tmp_path
):
    read = {
        "action": "storeMediaFile",
        "params": {"filename": "m.txt", "path": str(host_secret)},
    }
    export = {
        "action": "exportPackage",
        "params": {"deck": "Default", "path": str(tmp_path / "m.apkg")},
    }
    nested = {"action": "multi", "params": {"actions": [read, export]}}
    body = await _rpc(
        {
            "action": "multi",
            "version": 6,
            "params": {"actions": [read, nested, {"action": "version"}]},
        }
    )
    direct, (nested_read, nested_export), ok = body["result"]
    for refused in (direct, nested_read, nested_export):
        assert PATHS_FLAG in refused["error"]
    assert ok == 6
    assert not _media_file(served_wrapper, "m.txt").exists()
    assert not (tmp_path / "m.apkg").exists()


def test_wrapper_level_refusal_covers_callers_that_bypass_the_rpc_dispatcher(
    server_paths_forbidden, anki_wrapper, host_secret, tmp_path
):
    """MCP tools call the wrapper directly, so the guard must live there."""
    with pytest.raises(ValueError, match=PATHS_FLAG):
        anki_wrapper.store_media_file("x.txt", "", path=str(host_secret))
    with pytest.raises(ValueError, match=PATHS_FLAG):
        anki_wrapper.import_package(str(tmp_path / "in.apkg"))
    with pytest.raises(ValueError, match=PATHS_FLAG):
        anki_wrapper.export_package("Default", str(tmp_path / "out.apkg"))


def test_retrieve_media_file_cannot_escape_the_media_directory(
    server_paths_forbidden, anki_wrapper, host_secret
):
    media_dir = Path(anki_wrapper.get_media_dir_path())
    escape = os.path.relpath(host_secret, media_dir)
    assert anki_wrapper.retrieve_media_file(escape) is None
    assert anki_wrapper.retrieve_media_file(str(host_secret)) is None


def test_legacy_default_still_reads_server_paths_and_urls(anki_wrapper, host_secret, httpserver):
    anki_wrapper.store_media_file("via-path.txt", "", path=str(host_secret))
    assert _media_file(anki_wrapper, "via-path.txt").read_text() == "TOP-SECRET-HOST-CONTENT"

    httpserver.expect_request("/pic.png").respond_with_data(b"png-bytes")
    anki_wrapper.store_media_file("via-url.png", "", url=httpserver.url_for("/pic.png"))
    assert _media_file(anki_wrapper, "via-url.png").read_bytes() == b"png-bytes"
