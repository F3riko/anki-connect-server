"""Tests for config module."""

import pytest
from pydantic import ValidationError

from anki_connect_server.config import Config


def _config(**values: object) -> Config:
    """Build a Config from explicit values only (no .env file)."""
    return Config(**values, _env_file=None)  # type: ignore[call-arg]


def test_config_defaults():
    """Test that config has correct defaults."""
    from anki_connect_server.config import Config

    cfg = Config(COLLECTION_PATH="/test/path.anki2")
    assert cfg.PORT == 8765
    assert cfg.BIND == "127.0.0.1"


def test_config_custom_values():
    """Test custom configuration values."""
    from anki_connect_server.config import Config

    cfg = Config(PORT=9000, BIND="0.0.0.0", COLLECTION_PATH="/test/path.anki2")
    assert cfg.PORT == 9000
    assert cfg.BIND == "0.0.0.0"


def test_config_ankiweb():
    """Test AnkiWeb configuration."""
    from anki_connect_server.config import Config

    cfg = Config(
        COLLECTION_PATH="/test/path.anki2",
        ANKIWEB_USER="test@example.com",
        ANKIWEB_PASS="password123",
    )
    assert cfg.ANKIWEB_USER == "test@example.com"
    assert cfg.ANKIWEB_PASS == "password123"


def test_config_optional_ankiweb(monkeypatch):
    """Test that AnkiWeb config is optional when not set in env."""
    from anki_connect_server.config import Config

    monkeypatch.setenv("ANKICONNECT_COLLECTION_PATH", "/test/path.anki2")
    monkeypatch.delenv("ANKICONNECT_ANKIWEB_USER", raising=False)
    monkeypatch.delenv("ANKICONNECT_ANKIWEB_PASS", raising=False)

    cfg = Config(_env_file=None)  # type: ignore[call-arg]
    assert cfg.ANKIWEB_USER is None
    assert cfg.ANKIWEB_PASS is None


def test_validate_passes_with_collection_path():
    """Test that validation passes with collection path."""
    from anki_connect_server.config import Config

    cfg = Config(COLLECTION_PATH="/test/path.anki2")
    assert cfg.COLLECTION_PATH == "/test/path.anki2"


def test_config_loads_from_env(monkeypatch):
    """Config reads ANKICONNECT_* env vars.

    Construct a fresh Config() (not the cached singleton) so the test does not
    need importlib.reload, which would corrupt the @cache'd get_config() for
    the rest of the test session (other modules hold a reference to the
    pre-reload instance).
    """
    monkeypatch.setenv("ANKICONNECT_COLLECTION_PATH", "/env/path.anki2")
    monkeypatch.setenv("ANKICONNECT_PORT", "9000")
    monkeypatch.setenv("ANKICONNECT_ANKIWEB_USER", "env@user.com")
    monkeypatch.setenv("ANKICONNECT_ANKIWEB_URL", "https://sync.example.com")

    from anki_connect_server.config import Config

    cfg = Config(_env_file=None)  # type: ignore[call-arg]
    assert cfg.PORT == 9000
    assert cfg.COLLECTION_PATH == "/env/path.anki2"
    assert cfg.ANKIWEB_USER == "env@user.com"
    assert cfg.ANKIWEB_URL == "https://sync.example.com"


def test_config_defaults_empty_collection_path_to_temp():
    """An empty COLLECTION_PATH defaults to a random temp path instead of raising."""
    from anki_connect_server.config import Config

    cfg1 = Config(COLLECTION_PATH="", _env_file=None)  # type: ignore[call-arg]
    cfg2 = Config(COLLECTION_PATH="", _env_file=None)  # type: ignore[call-arg]
    assert cfg1.COLLECTION_PATH != ""
    assert cfg1.COLLECTION_PATH.endswith(".anki2")
    assert "anki-connect-server-" in cfg1.COLLECTION_PATH
    # Each invocation gets a distinct random filename so concurrent processes
    # don't contend for the same SQLite lock.
    assert cfg1.COLLECTION_PATH != cfg2.COLLECTION_PATH


def test_config_accepts_anki2_extension():
    """A .anki2 path is accepted without warning."""
    from anki_connect_server.config import Config

    cfg = Config(COLLECTION_PATH="/data/collection.anki2")
    assert cfg.COLLECTION_PATH == "/data/collection.anki2"


def test_config_accepts_extensionless_path():
    """An extensionless path (some users keep their collection without .anki2)
    is accepted so existing setups keep working."""
    from anki_connect_server.config import Config

    cfg = Config(COLLECTION_PATH="/data/anki_db")
    assert cfg.COLLECTION_PATH == "/data/anki_db"


def test_hardening_flags_default_to_legacy_compatible_values():
    """Flags-off means exactly these defaults: Andrew's instance must behave
    identically when none of the four hardening settings are configured."""
    cfg = _config(COLLECTION_PATH="/test/path.anki2")
    assert cfg.API_TOKEN is None
    assert cfg.ALLOW_REQUEST_CREDENTIALS is True
    assert cfg.ALLOW_SERVER_PATHS is True
    assert cfg.REQUIRE_COLLECTION_PATH is False


def test_hardening_flags_load_from_env(monkeypatch):
    monkeypatch.setenv("ANKICONNECT_COLLECTION_PATH", "/var/lib/x/collection.anki2")
    monkeypatch.setenv("ANKICONNECT_API_TOKEN", "s3cret-token")
    monkeypatch.setenv("ANKICONNECT_ALLOW_REQUEST_CREDENTIALS", "false")
    monkeypatch.setenv("ANKICONNECT_ALLOW_SERVER_PATHS", "false")
    monkeypatch.setenv("ANKICONNECT_REQUIRE_COLLECTION_PATH", "true")

    cfg = _config()
    assert cfg.API_TOKEN == "s3cret-token"
    assert cfg.ALLOW_REQUEST_CREDENTIALS is False
    assert cfg.ALLOW_SERVER_PATHS is False
    assert cfg.REQUIRE_COLLECTION_PATH is True


@pytest.mark.parametrize(
    "bad_path",
    ["", "   ", "collection.anki2", "./collection.anki2", "relative/dir/collection.anki2"],
)
def test_require_collection_path_rejects_blank_or_relative(bad_path):
    """With the flag on, a blank or relative path must fail startup instead of
    silently becoming a random temp collection or a CWD-relative file."""
    with pytest.raises(ValidationError, match="COLLECTION_PATH"):
        _config(COLLECTION_PATH=bad_path, REQUIRE_COLLECTION_PATH=True)


@pytest.mark.parametrize(
    "bad_path",
    ["/var/lib/anki/../../etc/collection.anki2", "/var/lib/anki/..", "/var/lib/a\x00b.anki2"],
)
def test_require_collection_path_rejects_unsafe_absolute_paths(bad_path):
    with pytest.raises(ValidationError, match="COLLECTION_PATH"):
        _config(COLLECTION_PATH=bad_path, REQUIRE_COLLECTION_PATH=True)


def test_require_collection_path_accepts_absolute_path_unchanged():
    cfg = _config(
        COLLECTION_PATH="/var/lib/anki-connect/t2/collection.anki2",
        REQUIRE_COLLECTION_PATH=True,
    )
    assert cfg.COLLECTION_PATH == "/var/lib/anki-connect/t2/collection.anki2"


def test_require_collection_path_never_falls_back_to_temp_collection(monkeypatch):
    """Missing env var with the flag on is a startup error, not a temp file."""
    monkeypatch.delenv("ANKICONNECT_COLLECTION_PATH", raising=False)
    monkeypatch.setenv("ANKICONNECT_REQUIRE_COLLECTION_PATH", "true")

    with pytest.raises(ValidationError, match="COLLECTION_PATH"):
        _config()


def test_validation_errors_do_not_echo_the_rejected_input():
    """pydantic prints input_value by default; configuration errors must not put
    raw setting values (a token, a path under a secret dir) into logs."""
    with pytest.raises(ValidationError) as excinfo:
        _config(COLLECTION_PATH="/x/../tok-DO-NOT-LEAK", REQUIRE_COLLECTION_PATH=True)
    rendered = str(excinfo.value) + repr(excinfo.value)
    assert "input_value" not in rendered
    assert "tok-DO-NOT-LEAK" not in rendered


@pytest.mark.parametrize("blank_token", ["", "   ", "\t"])
def test_blank_api_token_is_a_startup_error_not_disabled_auth(blank_token):
    """A set-but-empty token must never silently mean 'no authentication'."""
    with pytest.raises(ValidationError, match="API_TOKEN"):
        _config(COLLECTION_PATH="/test/path.anki2", API_TOKEN=blank_token)
