"""Behavioural tests for AnkiWeb fail-closed safe sync.

Enforces fail-closed safety policy:
- sync_collection must use sync_media=False.
- ALL full sync requirements (FULL_SYNC, FULL_DOWNLOAD, FULL_UPLOAD) and unsupported
  requirements must raise a clear explicit-human-direction-required SyncError.
- full_upload_or_download, close_for_full_sync, and media sync must NEVER be called
  during any full sync condition, preserving local and remote collections.
- Direct _full_download helper must be disabled and raise SyncError.
- Only after NORMAL_SYNC / NO_CHANGES is explicit sync_media(auth) started.
- Media poll failures must raise SyncError and not return success.
- Backend media error fields must raise SyncError.
- Timeout/failure must abort media and await inactive bounded before any close/reopen;
  if cannot prove idle, collection must not be closed/reopened (fail-closed).
- Active-media preflight must reject sync when media is active or unconfirmed.
- Concurrent sync locks are maintained.
"""

import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Any
from unittest.mock import Mock, patch

import pytest
from anki.sync_pb2 import SyncCollectionResponse

from anki_connect_server.sync import (
    CollectionSyncOutcome,
    SyncError,
    SyncResult,
)


@pytest.fixture
def patched_config(monkeypatch: pytest.MonkeyPatch):
    """Set ANKIWEB_USER/PASS on the cached config singleton, auto-restored."""
    from anki_connect_server.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg, "ANKIWEB_USER", "test")
    monkeypatch.setattr(cfg, "ANKIWEB_PASS", "test")
    return cfg


def _mock_media_status(
    active: bool,
    checked: str = "",
    added: str = "",
    removed: str = "",
    error: str | None = None,
):
    """Build a mock MediaSyncStatusResponse with .active and .progress counters."""
    status = Mock()
    status.active = active
    if error is not None:
        status.error = error
    else:
        status.error = ""
    if checked or added or removed:
        progress = Mock(checked=checked, added=added, removed=removed)
        status.HasField = Mock(side_effect=lambda f: f == "progress")
        status.progress = progress
    else:
        status.HasField = Mock(return_value=False)
    return status


def _make_mock_col(
    required: int,
    server_media_usn: int = 0,
    *,
    new_endpoint: str = "",
    server_message: str = "",
):
    """Build a Mock Collection whose sync_collection returns `required`.

    `required` is a SyncCollectionResponse enum value (or int).
    """
    mock_col = Mock()
    mock_auth = Mock(hkey="test_key")
    mock_result = Mock()
    mock_result.required = required
    mock_result.server_media_usn = server_media_usn
    mock_result.new_endpoint = new_endpoint
    mock_result.server_message = server_message

    mock_col.sync_login = Mock(return_value=mock_auth)
    mock_col.sync_collection = Mock(return_value=mock_result)
    mock_col.sync_media = Mock()
    # Default: inactive so preflight and wait return clean idle
    mock_col.media_sync_status = Mock(return_value=_mock_media_status(active=False))
    mock_col.close = Mock()
    mock_col.close_for_full_sync = Mock()
    mock_col.full_upload_or_download = Mock()
    mock_col.reopen = Mock()
    mock_col.abort_sync = Mock()
    mock_col.abort_media_sync = Mock()
    return mock_col, mock_auth, mock_result


@contextmanager
def _make_wrapper(mock_col: Any):
    """Yield an AnkiWrapper whose Collection is `mock_col`.

    The Collection patch and temp directory stay active for the duration of
    the with-block, so _reopen_collection (which calls Collection(...) again)
    keeps hitting the mock.
    """
    from anki_connect_server.anki_wrapper import AnkiWrapper

    with (
        patch("anki_connect_server.anki_wrapper.Collection", return_value=mock_col),
        tempfile.TemporaryDirectory() as tmpdir,
    ):
        collection_path = os.path.join(tmpdir, "test.anki2")
        yield AnkiWrapper(collection_path)


class TestSyncRequirementResolution:
    """Fail-closed resolution of collection sync requirements."""

    def test_full_sync_requires_explicit_direction(self, patched_config):
        """FULL_SYNC raises SyncError requiring explicit human direction and never downloads/starts media."""
        mock_col, mock_auth, _ = _make_mock_col(
            SyncCollectionResponse.FULL_SYNC, server_media_usn=42
        )
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="explicit human direction"):
                wrapper.sync_to_ankiweb()

        mock_col.sync_collection.assert_called_once_with(mock_auth, sync_media=False)
        mock_col.full_upload_or_download.assert_not_called()
        mock_col.close_for_full_sync.assert_not_called()
        mock_col.sync_media.assert_not_called()
        assert wrapper.collection_generation == 0

    def test_full_download_requires_explicit_direction(self, patched_config):
        """FULL_DOWNLOAD raises SyncError requiring explicit human direction and never downloads/starts media."""
        mock_col, mock_auth, _ = _make_mock_col(
            SyncCollectionResponse.FULL_DOWNLOAD, server_media_usn=42
        )
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="explicit human direction"):
                wrapper.sync_to_ankiweb()

        mock_col.sync_collection.assert_called_once_with(mock_auth, sync_media=False)
        mock_col.full_upload_or_download.assert_not_called()
        mock_col.close_for_full_sync.assert_not_called()
        mock_col.sync_media.assert_not_called()
        assert wrapper.collection_generation == 0

    def test_full_upload_requires_explicit_direction(self, patched_config):
        """FULL_UPLOAD raises SyncError requiring explicit human direction and never uploads/starts media."""
        mock_col, mock_auth, _ = _make_mock_col(
            SyncCollectionResponse.FULL_UPLOAD, server_media_usn=42
        )
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="explicit human direction"):
                wrapper.sync_to_ankiweb()

        mock_col.sync_collection.assert_called_once_with(mock_auth, sync_media=False)
        mock_col.full_upload_or_download.assert_not_called()
        mock_col.close_for_full_sync.assert_not_called()
        mock_col.sync_media.assert_not_called()
        assert wrapper.collection_generation == 0

    def test_unsupported_requirement_raises(self, patched_config):
        """Unsupported sync requirement raises SyncError and never starts media."""
        mock_col, mock_auth, _ = _make_mock_col(99)
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="Unsupported synchronization requirement"):
                wrapper.sync_to_ankiweb()

        mock_col.sync_collection.assert_called_once_with(mock_auth, sync_media=False)
        mock_col.sync_media.assert_not_called()
        assert wrapper.collection_generation == 0

    def test_normal_sync_starts_explicit_sync_media_and_reopens(self, patched_config):
        """NORMAL_SYNC uses sync_media=False, explicitly starts sync_media, and reopens."""
        mock_col, mock_auth, _ = _make_mock_col(SyncCollectionResponse.NORMAL_SYNC)
        with _make_wrapper(mock_col) as wrapper:
            result = wrapper.sync_to_ankiweb()

        assert result.collection.outcome is CollectionSyncOutcome.MERGED
        assert result.collection.local_data_replaced is False
        mock_col.sync_collection.assert_called_once_with(mock_auth, sync_media=False)
        mock_col.sync_media.assert_called_once_with(mock_auth)
        mock_col.close.assert_called()
        assert wrapper.collection_generation == 1

    def test_no_changes_starts_explicit_sync_media_and_reopens(self, patched_config):
        """NO_CHANGES uses sync_media=False, explicitly starts sync_media, and reopens."""
        mock_col, mock_auth, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        with _make_wrapper(mock_col) as wrapper:
            result = wrapper.sync_to_ankiweb()

        assert result.collection.outcome is CollectionSyncOutcome.NO_CHANGES
        mock_col.sync_collection.assert_called_once_with(mock_auth, sync_media=False)
        mock_col.sync_media.assert_called_once_with(mock_auth)
        mock_col.close.assert_called()
        assert wrapper.collection_generation == 1

    def test_new_endpoint_redirect_honoured_on_normal_sync(self, patched_config):
        """A sync endpoint redirect is applied to auth before calling sync_media."""
        mock_col, mock_auth, _ = _make_mock_col(
            SyncCollectionResponse.NORMAL_SYNC,
            new_endpoint="https://sync2.ankiweb.net",
        )
        with _make_wrapper(mock_col) as wrapper:
            wrapper.sync_to_ankiweb()

        assert mock_auth.endpoint == "https://sync2.ankiweb.net"
        mock_col.sync_media.assert_called_once_with(mock_auth)

    def test_server_message_propagated(self, patched_config):
        """server_message from the sync response is surfaced in SyncResult."""
        mock_col, _, _ = _make_mock_col(
            SyncCollectionResponse.NO_CHANGES, server_message="hello from server"
        )
        with _make_wrapper(mock_col) as wrapper:
            result = wrapper.sync_to_ankiweb()

        assert result.server_message == "hello from server"


class TestSyncSafety:
    """Concurrency, failure recovery, and abort behaviour."""

    def test_direct_full_download_helper_disabled(self):
        """Calling _full_download directly raises SyncError and touches no collection state."""
        mock_col = Mock()
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match=r"disabled by.*safety policy"):
                wrapper._full_download(Mock(), 0)  # type: ignore[reportPrivateUsage]

        mock_col.close_for_full_sync.assert_not_called()
        mock_col.full_upload_or_download.assert_not_called()

    def test_concurrent_sync_rejected(self, patched_config):
        """A second sync while one is in progress raises SyncError."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        with _make_wrapper(mock_col) as wrapper:
            assert wrapper._sync_lock.acquire(blocking=False) is True  # type: ignore[private-usage]
            try:
                with pytest.raises(SyncError, match="already in progress"):
                    wrapper.sync_to_ankiweb()
            finally:
                wrapper._sync_lock.release()  # type: ignore[private-usage]

            # After release, sync works again.
            wrapper.sync_to_ankiweb()

    def test_sync_collection_failure_raises_sync_error(self, patched_config):
        """If sync_collection itself fails, SyncError is raised and col is closed."""
        mock_col = Mock()
        mock_auth = Mock(hkey="test_key")
        mock_col.sync_login = Mock(return_value=mock_auth)
        mock_col.sync_collection = Mock(side_effect=RuntimeError("auth server down"))
        mock_col.close = Mock()
        mock_col.media_sync_status = Mock(return_value=_mock_media_status(active=False))
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="Collection synchronization failed"):
                wrapper.sync_to_ankiweb()

        mock_col.close.assert_called()

    def test_abort_sync_calls_both_abort_methods(self):
        """abort_sync calls col.abort_sync and col.abort_media_sync."""
        mock_col = Mock()
        with _make_wrapper(mock_col) as wrapper:
            wrapper.abort_sync()

        mock_col.abort_sync.assert_called_once()
        mock_col.abort_media_sync.assert_called_once()

    def test_abort_sync_swallows_errors(self):
        """abort_sync must not raise even if the underlying abort methods fail."""
        mock_col = Mock()
        mock_col.abort_sync = Mock(side_effect=RuntimeError("boom"))
        mock_col.abort_media_sync = Mock(side_effect=RuntimeError("boom2"))
        with _make_wrapper(mock_col) as wrapper:
            # Must not raise.
            wrapper.abort_sync()

        mock_col.abort_sync.assert_called_once()
        mock_col.abort_media_sync.assert_called_once()

    def test_error_logged_on_failure(self, patched_config, caplog):
        """Errors during sync are logged with the exception."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        mock_col.sync_collection = Mock(side_effect=ValueError("Test collection error"))
        with _make_wrapper(mock_col) as wrapper:
            with caplog.at_level(logging.ERROR):
                with pytest.raises(SyncError, match="Collection synchronization failed"):
                    wrapper.sync_to_ankiweb()

        assert "Test collection error" in caplog.text


class TestCollectionGeneration:
    """collection_generation increments whenever sync reopens the collection."""

    def test_starts_at_zero(self):
        """A fresh wrapper has collection_generation == 0."""
        mock_col = Mock()
        with _make_wrapper(mock_col) as wrapper:
            assert wrapper.collection_generation == 0

    def test_full_sync_does_not_increment(self, patched_config):
        """FULL_SYNC raises SyncError before any reopen, generation stays at 0."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.FULL_SYNC)
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="explicit human direction"):
                wrapper.sync_to_ankiweb()

        assert wrapper.collection_generation == 0

    def test_full_download_does_not_increment(self, patched_config):
        """FULL_DOWNLOAD raises SyncError before any reopen, generation stays at 0."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.FULL_DOWNLOAD)
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="explicit human direction"):
                wrapper.sync_to_ankiweb()

        assert wrapper.collection_generation == 0

    def test_full_upload_does_not_increment(self, patched_config):
        """FULL_UPLOAD raises SyncError before any reopen, so generation stays at 0."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.FULL_UPLOAD)
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="explicit human direction"):
                wrapper.sync_to_ankiweb()

        assert wrapper.collection_generation == 0

    def test_normal_sync_increments(self, patched_config):
        """NORMAL_SYNC reopens after media sync (+1)."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NORMAL_SYNC)
        with _make_wrapper(mock_col) as wrapper:
            wrapper.sync_to_ankiweb()

        assert wrapper.collection_generation == 1

    def test_no_changes_increments(self, patched_config):
        """NO_CHANGES reopens after media sync (+1)."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        with _make_wrapper(mock_col) as wrapper:
            wrapper.sync_to_ankiweb()

        assert wrapper.collection_generation == 1

    def test_repeated_syncs_accumulate(self, patched_config):
        """Each successful sync increments the generation by 1."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        with _make_wrapper(mock_col) as wrapper:
            wrapper.sync_to_ankiweb()
            assert wrapper.collection_generation == 1
            wrapper.sync_to_ankiweb()
            assert wrapper.collection_generation == 2
            wrapper.sync_to_ankiweb()
            assert wrapper.collection_generation == 3


class TestMediaSync:
    """sync_media_only, _wait_for_media, preflight, and bounded idle verification."""

    def test_sync_media_only_waits_for_completion(self, patched_config):
        """sync_media_only polls media_sync_status until inactive and returns counters."""
        mock_col = Mock()
        mock_auth = Mock(hkey="test_key")
        # Preflight: inactive. Poll 1: active. Poll 2: inactive with counters.
        mock_col.media_sync_status = Mock(
            side_effect=[
                _mock_media_status(active=False),
                _mock_media_status(active=True, checked="5", added="2", removed="1"),
                _mock_media_status(active=False, checked="5", added="2", removed="1"),
            ]
        )
        mock_col.sync_login = Mock(return_value=mock_auth)
        mock_col.sync_media = Mock()
        mock_col.abort_sync = Mock()
        mock_col.abort_media_sync = Mock()
        with _make_wrapper(mock_col) as wrapper:
            result = wrapper.sync_media_only()

        assert result.outcome == "completed"
        assert result.checked == "5"
        assert result.added == "2"
        assert result.removed == "1"
        mock_col.sync_media.assert_called_once_with(mock_auth)
        mock_col.abort_media_sync.assert_not_called()

    def test_sync_media_only_aborts_on_timeout(self, patched_config):
        """sync_media_only aborts and raises SyncError when media sync never finishes."""
        mock_col = Mock()
        mock_auth = Mock(hkey="test_key")
        mock_col.sync_login = Mock(return_value=mock_auth)
        mock_col.sync_media = Mock()
        # Preflight returns inactive; wait polls return active; abort wait returns inactive
        mock_col.media_sync_status = Mock(
            side_effect=[
                _mock_media_status(active=False),  # preflight
                _mock_media_status(active=True),  # polling in loop
                _mock_media_status(active=True),
                _mock_media_status(active=True),
                _mock_media_status(active=False),  # after abort
            ]
        )
        mock_col.abort_sync = Mock()
        mock_col.abort_media_sync = Mock()
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="timed out"):
                wrapper.sync_media_only(timeout=0.03, poll_interval=0.01)

        mock_col.abort_media_sync.assert_called()

    def test_sync_media_only_rejects_concurrent(self, patched_config):
        """A second media sync while one is in progress raises SyncError."""
        mock_col = Mock()
        mock_auth = Mock(hkey="test_key")
        mock_col.sync_login = Mock(return_value=mock_auth)
        mock_col.sync_media = Mock()
        mock_col.media_sync_status = Mock(return_value=_mock_media_status(active=False))
        with _make_wrapper(mock_col) as wrapper:
            assert wrapper._sync_lock.acquire(blocking=False) is True  # type: ignore[private-usage]
            try:
                with pytest.raises(SyncError, match="already in progress"):
                    wrapper.sync_media_only()
            finally:
                wrapper._sync_lock.release()  # type: ignore[private-usage]

    def test_media_poll_failure_raises_not_success(self, patched_config):
        """Media poll failure MUST raise SyncError, never return a fake successful result."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NORMAL_SYNC)
        # Preflight: inactive. Poll during wait: throws! Abort wait: returns inactive.
        mock_col.media_sync_status = Mock(
            side_effect=[
                _mock_media_status(active=False),  # preflight
                RuntimeError("media status poll broken"),  # polling failure
                _mock_media_status(active=False),  # abort wait
            ]
        )
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="Media synchronization status poll failed"):
                wrapper.sync_to_ankiweb()

        mock_col.abort_media_sync.assert_called()

    def test_backend_media_error_field_raises_sync_error(self, patched_config):
        """Backend media error field in status response aborts and raises SyncError."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NORMAL_SYNC)
        # Preflight: inactive. Poll: has error. Abort wait: inactive.
        mock_col.media_sync_status = Mock(
            side_effect=[
                _mock_media_status(active=False),
                _mock_media_status(active=True, error="network socket closed by remote"),
                _mock_media_status(active=False),
            ]
        )
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="network socket closed"):
                wrapper.sync_to_ankiweb(timeout=0.1, poll_interval=0.01)

        mock_col.abort_media_sync.assert_called()

    def test_media_cannot_prove_idle_fails_closed_no_reopen(self, patched_config):
        """If media abort cannot prove idle, collection is NOT closed/reopened and subsequent sync rejected."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NORMAL_SYNC)
        # Preflight: inactive.
        # Wait poll: timeout or continuous active that never becomes inactive during abort wait.
        mock_col.media_sync_status = Mock(
            side_effect=[
                _mock_media_status(active=False),  # preflight
                _mock_media_status(active=True),  # wait poll
                _mock_media_status(active=True),  # abort wait keeps reporting active
                _mock_media_status(active=True),
                _mock_media_status(active=True),
                _mock_media_status(active=True),
            ]
        )
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="timed out"):
                wrapper.sync_to_ankiweb(timeout=0.02, poll_interval=0.01)

            # Collection must NOT have been closed/reopened because media was not proven idle!
            mock_col.close.assert_not_called()
            mock_col.reopen.assert_not_called()
            assert wrapper.collection_generation == 0

            # Subsequent call must reject via active-media preflight
            with pytest.raises(SyncError, match=r"Media synchronization.*active"):
                wrapper.sync_to_ankiweb()

    def test_active_media_preflight_rejects_initial_sync(self, patched_config):
        """Preflight rejects sync immediately if media is already active."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        mock_col.media_sync_status = Mock(return_value=_mock_media_status(active=True))
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="Media synchronization is currently active"):
                wrapper.sync_to_ankiweb()

        mock_col.sync_collection.assert_not_called()
        mock_col.sync_media.assert_not_called()

    def test_active_media_preflight_rejects_when_status_check_fails(self, patched_config):
        """Preflight fails closed if media status cannot be queried."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        mock_col.media_sync_status = Mock(side_effect=RuntimeError("database locked"))
        with _make_wrapper(mock_col) as wrapper:
            with pytest.raises(SyncError, match="Cannot verify media synchronization state"):
                wrapper.sync_to_ankiweb()

        mock_col.sync_collection.assert_not_called()


class TestSyncResultStructure:
    """SyncResult is a structured Pydantic model, not a string."""

    def test_result_is_pydantic_model(self, patched_config):
        from pydantic import BaseModel

        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES)
        with _make_wrapper(mock_col) as wrapper:
            result = wrapper.sync_to_ankiweb()

        assert isinstance(result, BaseModel)
        assert isinstance(result, SyncResult)
        assert result.status == "completed"

    def test_result_serialises_to_json(self, patched_config):
        """SyncResult can be serialised to JSON for the REST/MCP response."""
        mock_col, _, _ = _make_mock_col(SyncCollectionResponse.NO_CHANGES, server_message="ok")
        with _make_wrapper(mock_col) as wrapper:
            result = wrapper.sync_to_ankiweb()

        dumped = result.model_dump(mode="json", exclude_none=True)
        assert dumped["status"] == "completed"
        assert dumped["collection"]["outcome"] == "no_changes"
        assert dumped["server_message"] == "ok"
