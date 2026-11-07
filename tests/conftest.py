"""Tests configuration."""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from anki.collection import Collection

from anki_connect_server.anki_wrapper import AnkiWrapper


@pytest.fixture(autouse=True)
def isolate_test_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run each test from a clean tmp_path so the repo's .env (which may hold
    real AnkiWeb credentials) is not picked up by Config() / pydantic-settings,
    which read .env from the current working directory.

    Provide a placeholder COLLECTION_PATH so Config() validates without the
    repo's .env; individual tests that build a real AnkiWrapper use the
    dedicated ``anki_wrapper`` fixture which points at a temp collection.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANKICONNECT_COLLECTION_PATH", str(tmp_path / "fake.anki2"))


@pytest.fixture(autouse=True)
def forbid_real_ankiweb_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may ever reach AnkiWeb: a real Collection must fail loudly on login.

    Tests exercising sync mock the collection (or patch ``sync_login`` on the
    instance, which takes precedence over this class-level guard).
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("tests must not contact AnkiWeb; mock Collection.sync_login")

    monkeypatch.setattr(Collection, "sync_login", refuse)


@pytest.fixture
def anki_wrapper() -> Iterator[AnkiWrapper]:
    """Create a real AnkiWrapper with temporary collection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        collection_path = Path(tmpdir) / "test.anki2"
        media_path = collection_path.with_name(collection_path.stem + "-media")
        media_path.mkdir(parents=True, exist_ok=True)

        wrapper = AnkiWrapper(str(collection_path))

        yield wrapper

        wrapper.close()
