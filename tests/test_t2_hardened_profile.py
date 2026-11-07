"""All four hardening settings together (the t2 profile) plus safe-sync regressions.

These pin that the pre-existing safe.2 behaviour (FULL_* refusal, awaited media
completion, JSON-safe wire output) is unchanged when the instance is hardened.
They are characterization tests: they are expected to pass on first run, and the
mutation checks recorded in the maker report show they fail when the guarded
behaviour is removed.
"""

import base64
from unittest.mock import Mock, patch

import pytest
from anki.sync_pb2 import SyncCollectionResponse
from fastapi.testclient import TestClient

from anki_connect_server.api import app
from anki_connect_server.config import get_config

TOKEN = "t2-profile-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def t2_profile(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "API_TOKEN", TOKEN)
    monkeypatch.setattr(cfg, "ALLOW_REQUEST_CREDENTIALS", False)
    monkeypatch.setattr(cfg, "ALLOW_SERVER_PATHS", False)
    monkeypatch.setattr(cfg, "REQUIRE_COLLECTION_PATH", True)
    monkeypatch.setattr(cfg, "ANKIWEB_USER", "vlada@example.com")
    monkeypatch.setattr(cfg, "ANKIWEB_PASS", "configured-in-env")


@pytest.fixture
def served_wrapper(anki_wrapper):
    app.state.anki_wrapper = anki_wrapper
    yield anki_wrapper
    app.state.anki_wrapper = None


def _idle_media_status() -> Mock:
    status = Mock(active=False, error="")
    status.HasField = Mock(return_value=False)
    return status


def _mock_sync_col(required) -> Mock:
    col = Mock()
    col.sync_login = Mock(return_value=Mock(hkey="k"))
    col.sync_collection = Mock(
        return_value=Mock(required=required, server_media_usn=0, new_endpoint="", server_message="")
    )
    col.media_sync_status = Mock(return_value=_idle_media_status())
    return col


@pytest.fixture
def mock_col_wrapper(tmp_path):
    """Build a wrapper whose Collection (including post-sync reopens) is a Mock.

    The patch must stay active for the whole test: a successful sync closes and
    reopens the collection, which would otherwise construct a real Collection.
    """
    from anki_connect_server.anki_wrapper import AnkiWrapper

    with patch("anki_connect_server.anki_wrapper.Collection") as collection_cls:

        def build(required) -> tuple[AnkiWrapper, Mock]:
            col = _mock_sync_col(required)
            collection_cls.return_value = col
            wrapper = AnkiWrapper(str(tmp_path / "disposable.anki2"))
            app.state.anki_wrapper = wrapper
            return wrapper, col

        yield build
    app.state.anki_wrapper = None


def test_all_four_settings_are_enforced_together(t2_profile, served_wrapper, tmp_path):
    client = TestClient(app)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")

    assert client.post("/api", json={"action": "version", "version": 6}).status_code == 401
    assert client.get("/health").status_code == 200

    ok = client.post("/api", json={"action": "version", "version": 6}, headers=AUTH)
    assert ok.json() == {"result": 6, "error": None}

    override = client.post(
        "/api",
        json={"action": "sync", "version": 6, "params": {"username": "x", "password": "y"}},
        headers=AUTH,
    ).json()
    assert "ANKICONNECT_ALLOW_REQUEST_CREDENTIALS" in override["error"]

    read = client.post(
        "/api",
        json={
            "action": "storeMediaFile",
            "version": 6,
            "params": {"filename": "a.txt", "path": str(secret)},
        },
        headers=AUTH,
    ).json()
    assert "ANKICONNECT_ALLOW_SERVER_PATHS" in read["error"]

    stored = client.post(
        "/api",
        json={
            "action": "storeMediaFile",
            "version": 6,
            "params": {"filename": "b.txt", "data": base64.b64encode(b"ok").decode()},
        },
        headers=AUTH,
    ).json()
    assert stored == {"result": None, "error": None}


@pytest.mark.parametrize(
    ("required", "message"),
    [
        (SyncCollectionResponse.FULL_SYNC, "Full sync required"),
        (SyncCollectionResponse.FULL_DOWNLOAD, "Full download required"),
        (SyncCollectionResponse.FULL_UPLOAD, "Full upload required"),
    ],
)
def test_full_sync_variants_are_still_refused_when_hardened(
    t2_profile, mock_col_wrapper, required, message
):
    _, col = mock_col_wrapper(required)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api", json={"action": "sync", "version": 6}, headers=AUTH
    )
    assert response.status_code == 500
    assert message in response.json()["error"]
    assert "explicit human direction required" in response.json()["error"]
    col.close_for_full_sync.assert_not_called()
    col.full_upload_or_download.assert_not_called()
    col.sync_media.assert_not_called()
    assert col.sync_login.call_args.kwargs["username"] == "vlada@example.com"


def test_hardened_sync_awaits_media_and_returns_json_objects_not_pairs(
    t2_profile, mock_col_wrapper
):
    _, col = mock_col_wrapper(SyncCollectionResponse.NO_CHANGES)
    client = TestClient(app, raise_server_exceptions=False)

    body = client.post("/api", json={"action": "sync", "version": 6}, headers=AUTH).json()
    nested = client.post(
        "/api",
        json={"action": "multi", "version": 6, "params": {"actions": [{"action": "sync"}]}},
        headers=AUTH,
    ).json()

    for result in (body["result"], nested["result"][0]):
        assert isinstance(result, dict)
        assert result["status"] == "completed"
        assert result["collection"]["outcome"] == "no_changes"
        assert result["collection"]["local_data_replaced"] is False
        assert result["media"]["outcome"] == "completed"
    # media completion was awaited via status polling, not assumed
    assert col.sync_media.call_count == 2
    assert col.media_sync_status.call_count >= 2
