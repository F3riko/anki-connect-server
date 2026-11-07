import posixpath
import secrets
import tempfile
from functools import cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_collection_path() -> str:
    """Return a temp path with a random filename for a fresh Anki collection.

    Used when ``ANKICONNECT_COLLECTION_PATH`` is not configured. The random
    filename ensures each process gets its own collection, so concurrent MCP
    instances (e.g. spawned by a client) don't contend for the same SQLite lock.
    """
    return str(Path(tempfile.gettempdir()) / f"anki-connect-server-{secrets.token_hex(8)}.anki2")


def _required_collection_path_problem(value: str) -> str | None:
    """Describe why ``value`` is unusable as an explicitly required path, else None."""
    if not value.strip():
        return "must be set when ANKICONNECT_REQUIRE_COLLECTION_PATH is enabled"
    if "\x00" in value:
        return "must not contain NUL bytes"
    if not posixpath.isabs(value):
        return "must be an absolute path"
    if ".." in value.split("/"):
        return "must not contain '..' segments"
    return None


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="ANKICONNECT_",
        # Validation errors otherwise echo the rejected input value (and, for
        # model-level errors, every setting) into tracebacks and logs.
        hide_input_in_errors=True,
    )

    PORT: int = 8765
    BIND: str = "127.0.0.1"

    # Declared before COLLECTION_PATH on purpose: its validator reads this flag
    # from ``info.data``, which only holds fields validated earlier.
    REQUIRE_COLLECTION_PATH: bool = False
    COLLECTION_PATH: str = ""

    ANKIWEB_USER: str | None = None
    ANKIWEB_PASS: str | None = None

    ANKIWEB_URL: str | None = None

    # Instance hardening. The defaults are legacy-compatible: with none of these
    # set the server behaves exactly as before.
    API_TOKEN: str | None = None
    ALLOW_REQUEST_CREDENTIALS: bool = True
    ALLOW_SERVER_PATHS: bool = True

    @field_validator("COLLECTION_PATH")
    @classmethod
    def _validate_collection_path(cls, v: str, info: ValidationInfo) -> str:
        if info.data.get("REQUIRE_COLLECTION_PATH"):
            problem = _required_collection_path_problem(v)
            if problem:
                raise ValueError(f"ANKICONNECT_COLLECTION_PATH {problem}")
            return v
        if not v:
            return _default_collection_path()
        return v

    @field_validator("API_TOKEN")
    @classmethod
    def _validate_api_token(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            # An empty token must not silently mean "authentication disabled".
            raise ValueError("ANKICONNECT_API_TOKEN must not be empty when set")
        return v


@cache
def get_config() -> Config:
    return Config()
