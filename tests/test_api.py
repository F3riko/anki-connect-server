from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from anki_connect_server.api import app
from anki_connect_server.sync import (
    CollectionSyncOutcome,
    CollectionSyncResult,
    MediaSyncResult,
    SyncResult,
)


@pytest.fixture
def app_with_wrapper(anki_wrapper):
    """Attach a real AnkiWrapper to app.state for the duration of the test."""
    app.state.anki_wrapper = anki_wrapper
    yield anki_wrapper
    app.state.anki_wrapper = None


@pytest.mark.asyncio
async def test_root_endpoint(app_with_wrapper):
    """Test root endpoint returns health message."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "version", "version": 6})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_endpoint(app_with_wrapper):
    """Test health check endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_version_action(app_with_wrapper):
    """Test version action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "version", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == 6
        assert data["error"] is None


@pytest.mark.asyncio
async def test_deck_names_action(app_with_wrapper):
    """Test deckNames action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "deckNames", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert "Default" in data["result"]
        assert data["error"] is None


@pytest.mark.asyncio
async def test_deck_names_and_ids_action(app_with_wrapper):
    """Test deckNamesAndIds action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "deckNamesAndIds", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert "Default" in data["result"]


@pytest.mark.asyncio
async def test_create_deck_action(app_with_wrapper):
    """Test createDeck action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "createDeck", "version": 6, "params": {"deck": "NewDeck"}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] > 0


@pytest.mark.asyncio
async def test_model_names_action(app_with_wrapper):
    """Test modelNames action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "modelNames", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert "Basic" in data["result"]


@pytest.mark.asyncio
async def test_model_field_names_action(app_with_wrapper):
    """Test modelFieldNames action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "modelFieldNames", "version": 6, "params": {"modelName": "Basic"}}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Front" in data["result"]
        assert "Back" in data["result"]


@pytest.mark.asyncio
async def test_add_note_action(app_with_wrapper):
    """Test addNote action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/",
            json={
                "action": "addNote",
                "version": 6,
                "params": {
                    "note": {
                        "deckName": "Default",
                        "modelName": "Basic",
                        "fields": {"Front": "Hello", "Back": "World"},
                    }
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] is not None


@pytest.mark.asyncio
async def test_can_add_notes_with_error_detail_action(app_with_wrapper):
    """Test canAddNotesWithErrorDetail action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/",
            json={
                "action": "canAddNotesWithErrorDetail",
                "version": 6,
                "params": {
                    "notes": [
                        {
                            "deckName": "Default",
                            "modelName": "Basic",
                            "fields": {"Front": "ApiCanAddDetail", "Back": "World"},
                        }
                    ]
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == [{"canAdd": True}]
        assert data["error"] is None


@pytest.mark.asyncio
async def test_find_notes_action(app_with_wrapper):
    """Test findNotes action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "findNotes", "version": 6, "params": {"query": "deck:Default"}}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["result"], list)


@pytest.mark.asyncio
async def test_notes_info_action(app_with_wrapper):
    """Test notesInfo action."""
    anki_wrapper = app_with_wrapper
    note_id = anki_wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Test", "Back": "Test"}}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "notesInfo", "version": 6, "params": {"notes": [note_id]}}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["result"]) == 1
        assert data["result"][0]["noteId"] == note_id


@pytest.mark.asyncio
async def test_delete_notes_action(app_with_wrapper):
    """Test deleteNotes action."""
    anki_wrapper = app_with_wrapper
    note_id = anki_wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Test", "Back": "Test"}}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "deleteNotes", "version": 6, "params": {"notes": [note_id]}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] is None


@pytest.mark.asyncio
async def test_find_cards_action(app_with_wrapper):
    """Test findCards action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "findCards", "version": 6, "params": {"query": "deck:Default"}}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["result"], list)


@pytest.mark.asyncio
async def test_cards_info_action(app_with_wrapper):
    """Test cardsInfo action."""
    anki_wrapper = app_with_wrapper
    note_id = anki_wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Test", "Back": "Test"}}
    )
    card_ids = anki_wrapper.find_cards(f"nid:{note_id}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "cardsInfo", "version": 6, "params": {"cards": card_ids}}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["result"]) > 0


@pytest.mark.asyncio
async def test_suspend_action(app_with_wrapper):
    """Test suspend action."""
    anki_wrapper = app_with_wrapper
    note_id = anki_wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Test", "Back": "Test"}}
    )
    card_ids = anki_wrapper.find_cards(f"nid:{note_id}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "suspend", "version": 6, "params": {"cards": card_ids}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] is True


@pytest.mark.asyncio
async def test_unsuspend_action(app_with_wrapper):
    """Test unsuspend action."""
    anki_wrapper = app_with_wrapper
    note_id = anki_wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Test", "Back": "Test"}}
    )
    card_ids = anki_wrapper.find_cards(f"nid:{note_id}")
    anki_wrapper.suspend(card_ids)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", json={"action": "unsuspend", "version": 6, "params": {"cards": card_ids}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] is True


@pytest.mark.asyncio
async def test_get_tags_action(app_with_wrapper):
    """Test getTags action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "getTags", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["result"], list)


@pytest.mark.asyncio
async def test_add_and_remove_tags_action(app_with_wrapper):
    """Test addTags and removeTags actions end-to-end."""
    anki_wrapper = app_with_wrapper
    note_id = anki_wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Test", "Back": "Test"}}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/",
            json={
                "action": "addTags",
                "version": 6,
                "params": {"notes": [note_id], "tags": "foo bar"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] is None
        assert sorted(anki_wrapper.col.get_note(note_id).tags) == ["bar", "foo"]

        response = await client.post(
            "/",
            json={
                "action": "removeTags",
                "version": 6,
                "params": {"notes": [note_id], "tags": "bar"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] is None
        assert anki_wrapper.col.get_note(note_id).tags == ["foo"]


@pytest.mark.asyncio
async def test_get_media_dir_path_action(app_with_wrapper):
    """Test getMediaDirPath action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "getMediaDirPath", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert data["result"] is not None


@pytest.mark.asyncio
async def test_multi_action(app_with_wrapper):
    """Test multi action."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/",
            json={
                "action": "multi",
                "version": 6,
                "params": {
                    "actions": [
                        {"action": "deckNames", "params": {}},
                        {"action": "modelNames", "params": {}},
                    ]
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["result"]) == 2


@pytest.mark.asyncio
async def test_legacy_version_bare_result(app_with_wrapper):
    """Version ≤4 requests receive the bare result with no envelope, per the
    AnkiConnect spec (Yomitan probes at version 2 and relies on this)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for version in (2, 4):
            response = await client.post("/", json={"action": "deckNames", "version": version})
            assert response.status_code == 200
            assert "Default" in response.json()

        response = await client.post("/", json={"action": "version", "version": 2})
        assert response.json() == 6


@pytest.mark.asyncio
async def test_missing_version_defaults_to_legacy_envelope_free_response(app_with_wrapper):
    """A missing version field defaults to 4, so the bare result is returned."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "deckNames"})
        assert response.status_code == 200
        assert "Default" in response.json()


@pytest.mark.asyncio
async def test_legacy_version_error_envelope(app_with_wrapper):
    """Version ≤4 failures still return the {result, error} envelope, matching
    upstream format_exception_reply."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "unknownAction", "version": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["result"] is None
        assert "Unsupported action" in data["error"]


@pytest.mark.asyncio
async def test_version_6_envelope(app_with_wrapper):
    """Version >4 requests keep the standard {result, error} envelope."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "deckNames", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert "Default" in data["result"]
        assert data["error"] is None


@pytest.mark.asyncio
async def test_unknown_action(app_with_wrapper):
    """Test unknown action returns error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "unknownAction", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert data["error"] is not None
        assert "Unsupported action" in data["error"]


@pytest.mark.asyncio
async def test_server_error_returns_500(app_with_wrapper, monkeypatch):
    """Unexpected (non-ValueError) exceptions must surface as HTTP 500, not be
    swallowed into a 200 with an error field. A corrupted-collection crash is
    a server fault, not a client error."""
    from anki_connect_server import handlers

    async def boom(wrapper, params):
        raise RuntimeError("collection is corrupted")

    monkeypatch.setitem(handlers.ACTION_HANDLERS, "boom", boom)
    # raise_server_exceptions=False lets the app's exception handler turn the
    # RuntimeError into a 500 response instead of the test transport re-raising.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/", json={"action": "boom", "version": 6})
        assert response.status_code == 500


@pytest.mark.asyncio
async def test_validation_error_returns_200_with_error(app_with_wrapper):
    """Client errors (ValueError subclass) are reported in-body with HTTP 200
    per the AnkiConnect convention so existing clients keep working."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # findNotes requires a 'query' param; missing it raises ValidationError.
        response = await client.post("/", json={"action": "findNotes", "version": 6})
        assert response.status_code == 200
        data = response.json()
        assert data["error"] is not None
        assert "query" in data["error"]


@pytest.mark.asyncio
async def test_invalid_json(app_with_wrapper):
    """Test invalid JSON request."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/", content="invalid json", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_app_lifespan_creates_and_closes_wrapper(monkeypatch):
    """app_lifespan constructs an AnkiWrapper on startup and closes it on shutdown.

    The ASGITransport-based tests bypass the lifespan (they set
    app.state.anki_wrapper directly), so this exercises the lifespan context
    manager in isolation to cover the create/close path.
    """
    from anki_connect_server.api import app, app_lifespan

    class FakeWrapper:
        def __init__(self, path: str) -> None:
            self.path = path
            self.closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        "anki_connect_server.api.create_anki_wrapper",
        lambda config=None: FakeWrapper("/fake.anki2"),
    )

    # Drive the lifespan async context manager directly.
    async with app_lifespan(app):
        wrapper = getattr(app.state, "anki_wrapper", None)
        assert wrapper is not None
        assert isinstance(wrapper, FakeWrapper)
        assert wrapper.closed is False

    # After exiting the lifespan, the wrapper is closed and state cleared.
    assert wrapper.closed is True
    assert getattr(app.state, "anki_wrapper", None) is None


@pytest.mark.asyncio
async def test_app_lifespan_handles_shutdown_when_wrapper_missing(monkeypatch):
    """app_lifespan's finally tolerates a missing wrapper (e.g. startup failed)."""
    from anki_connect_server.api import app, app_lifespan

    # Make create_anki_wrapper raise so app.state.anki_wrapper is never set.
    def boom(config=None):
        raise RuntimeError("startup failed")

    monkeypatch.setattr("anki_connect_server.api.create_anki_wrapper", boom)

    with pytest.raises(RuntimeError, match="startup failed"):
        async with app_lifespan(app):
            pass

    # State was never set; the finally does not raise.
    assert getattr(app.state, "anki_wrapper", None) is None


@pytest.fixture
def mock_sync_wrapper():
    """Attach a mock AnkiWrapper returning typed SyncResult and MediaSyncResult."""
    wrapper = MagicMock()
    wrapper.sync_to_ankiweb.return_value = SyncResult(
        status="completed",
        collection=CollectionSyncResult(
            outcome=CollectionSyncOutcome.NO_CHANGES,
            download_reason=None,
            local_data_replaced=False,
        ),
        media=MediaSyncResult(
            outcome="completed",
            checked="Checked:0",
            added="Added:0up0down",
            removed="Removed:0up0down",
        ),
        server_message=None,
    )
    wrapper.sync_media_only.return_value = MediaSyncResult(
        outcome="completed",
        checked="Checked:0",
        added="Added:0up0down",
        removed="Removed:0up0down",
    )
    app.state.anki_wrapper = wrapper
    yield wrapper
    app.state.anki_wrapper = None


def test_sync_action_wire_serialization_root_and_api(mock_sync_wrapper):
    """Test / and /api sync with typed mocked wrapper output returns a JSON object."""
    client = TestClient(app)
    expected_sync = {
        "status": "completed",
        "collection": {
            "outcome": "no_changes",
            "download_reason": None,
            "local_data_replaced": False,
        },
        "media": {
            "outcome": "completed",
            "checked": "Checked:0",
            "added": "Added:0up0down",
            "removed": "Removed:0up0down",
        },
        "server_message": None,
    }

    # POST / with version 6
    resp_root = client.post("/", json={"action": "sync", "version": 6})
    assert resp_root.status_code == 200
    data_root = resp_root.json()
    assert isinstance(data_root["result"], dict)
    assert data_root == {"result": expected_sync, "error": None}

    # POST /api with version 6
    resp_api = client.post("/api", json={"action": "sync", "version": 6})
    assert resp_api.status_code == 200
    data_api = resp_api.json()
    assert isinstance(data_api["result"], dict)
    assert data_api == {"result": expected_sync, "error": None}


def test_sync_media_action_wire_serialization_root_and_api(mock_sync_wrapper):
    """Test / and /api syncMedia with typed mocked wrapper output returns a JSON object."""
    client = TestClient(app)
    expected_media = {
        "outcome": "completed",
        "checked": "Checked:0",
        "added": "Added:0up0down",
        "removed": "Removed:0up0down",
    }

    # POST / with version 6
    resp_root = client.post("/", json={"action": "syncMedia", "version": 6})
    assert resp_root.status_code == 200
    data_root = resp_root.json()
    assert isinstance(data_root["result"], dict)
    assert data_root == {"result": expected_media, "error": None}

    # POST /api with version 6
    resp_api = client.post("/api", json={"action": "syncMedia", "version": 6})
    assert resp_api.status_code == 200
    data_api = resp_api.json()
    assert isinstance(data_api["result"], dict)
    assert data_api == {"result": expected_media, "error": None}


def test_multi_action_nested_wire_serialization(mock_sync_wrapper):
    """Test multi and nested multi actions serialize nested Pydantic models as JSON objects."""
    client = TestClient(app)
    expected_sync = {
        "status": "completed",
        "collection": {
            "outcome": "no_changes",
            "download_reason": None,
            "local_data_replaced": False,
        },
        "media": {
            "outcome": "completed",
            "checked": "Checked:0",
            "added": "Added:0up0down",
            "removed": "Removed:0up0down",
        },
        "server_message": None,
    }
    expected_media = {
        "outcome": "completed",
        "checked": "Checked:0",
        "added": "Added:0up0down",
        "removed": "Removed:0up0down",
    }

    # Batch multi containing syncMedia and sync
    resp = client.post(
        "/api",
        json={
            "action": "multi",
            "version": 6,
            "params": {"actions": [{"action": "syncMedia"}, {"action": "sync"}]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["result"], list)
    assert isinstance(data["result"][0], dict)
    assert isinstance(data["result"][1], dict)
    assert data == {"result": [expected_media, expected_sync], "error": None}

    # Nested multi (multi inside multi)
    resp_nested = client.post(
        "/",
        json={
            "action": "multi",
            "version": 6,
            "params": {
                "actions": [
                    {
                        "action": "multi",
                        "params": {"actions": [{"action": "sync"}]},
                    }
                ]
            },
        },
    )
    assert resp_nested.status_code == 200
    data_nested = resp_nested.json()
    assert isinstance(data_nested["result"], list)
    assert isinstance(data_nested["result"][0], list)
    assert isinstance(data_nested["result"][0][0], dict)
    assert data_nested == {"result": [[expected_sync]], "error": None}


def test_legacy_v4_bare_object_serialization(mock_sync_wrapper):
    """Test legacy version <= 4 requests return bare JSON objects, not envelopes or pair lists."""
    client = TestClient(app)
    expected_sync = {
        "status": "completed",
        "collection": {
            "outcome": "no_changes",
            "download_reason": None,
            "local_data_replaced": False,
        },
        "media": {
            "outcome": "completed",
            "checked": "Checked:0",
            "added": "Added:0up0down",
            "removed": "Removed:0up0down",
        },
        "server_message": None,
    }
    expected_media = {
        "outcome": "completed",
        "checked": "Checked:0",
        "added": "Added:0up0down",
        "removed": "Removed:0up0down",
    }

    # POST / with explicit version 4
    resp_v4_root = client.post("/", json={"action": "sync", "version": 4})
    assert resp_v4_root.status_code == 200
    data_v4_root = resp_v4_root.json()
    assert isinstance(data_v4_root, dict)
    assert data_v4_root == expected_sync

    # POST /api with explicit version 4
    resp_v4_api = client.post("/api", json={"action": "sync", "version": 4})
    assert resp_v4_api.status_code == 200
    data_v4_api = resp_v4_api.json()
    assert isinstance(data_v4_api, dict)
    assert data_v4_api == expected_sync

    # Missing version defaults to 4
    resp_default = client.post("/api", json={"action": "syncMedia"})
    assert resp_default.status_code == 200
    data_default = resp_default.json()
    assert isinstance(data_default, dict)
    assert data_default == expected_media


def test_error_envelopes_unchanged_over_http(mock_sync_wrapper):
    """Test error envelopes remain unchanged across versions and endpoints."""
    client = TestClient(app)

    # Unknown action at version 6 returns error envelope
    resp_v6 = client.post("/", json={"action": "noSuchAction", "version": 6})
    assert resp_v6.status_code == 200
    data_v6 = resp_v6.json()
    assert data_v6 == {"result": None, "error": "Unsupported action: noSuchAction"}

    # Unknown action at legacy version 4 returns error envelope
    resp_v4 = client.post("/", json={"action": "noSuchAction", "version": 4})
    assert resp_v4.status_code == 200
    data_v4 = resp_v4.json()
    assert data_v4 == {"result": None, "error": "Unsupported action: noSuchAction"}

    # Validation error at version 6 returns error envelope
    resp_val_v6 = client.post("/api", json={"action": "findNotes", "version": 6, "params": {}})
    assert resp_val_v6.status_code == 200
    data_val_v6 = resp_val_v6.json()
    assert data_val_v6["result"] is None
    assert "query" in data_val_v6["error"]

    # Validation error at version 4 returns error envelope
    resp_val_v4 = client.post("/api", json={"action": "findNotes", "version": 4, "params": {}})
    assert resp_val_v4.status_code == 200
    data_val_v4 = resp_val_v4.json()
    assert data_val_v4["result"] is None
    assert "query" in data_val_v4["error"]

    # Unknown action inside multi batch returns error string per-action
    resp_multi_err = client.post(
        "/api",
        json={
            "action": "multi",
            "version": 6,
            "params": {"actions": [{"action": "unknownSubAction"}]},
        },
    )
    assert resp_multi_err.status_code == 200
    data_multi_err = resp_multi_err.json()
    assert data_multi_err == {
        "result": [{"error": "Unknown action: unknownSubAction"}],
        "error": None,
    }
