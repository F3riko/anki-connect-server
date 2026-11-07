"""Request-level hardening checks driven by the instance settings.

These run inside AnkiWrapper, below the REST dispatcher, ``multi`` and the MCP
tools, so no entry point (including a nested ``multi``) can bypass them.
Refusals are ``ValueError`` so the API reports them as client-facing errors.
"""

from anki_connect_server.config import get_config


def reject_request_credentials(
    username: str | None, password: str | None, endpoint: str | None
) -> None:
    """Refuse per-request AnkiWeb username/password/endpoint overrides when disabled.

    ``None`` means "not supplied"; any other value, including an empty string, is
    refused rather than silently ignored.
    """
    if get_config().ALLOW_REQUEST_CREDENTIALS:
        return
    supplied = [
        name
        for name, value in (("username", username), ("password", password), ("endpoint", endpoint))
        if value is not None
    ]
    if supplied:
        raise ValueError(
            f"Request parameter(s) {', '.join(supplied)} are disabled by server policy "
            "(ANKICONNECT_ALLOW_REQUEST_CREDENTIALS=false)"
        )


def _refuse_server_paths(what: str) -> ValueError:
    return ValueError(f"{what} disabled by server policy (ANKICONNECT_ALLOW_SERVER_PATHS=false)")


def reject_server_media_sources(url: str, path: str) -> None:
    """Refuse server-side media sources (URL fetch, local file read) when disabled.

    Checked even when ``data`` is also supplied, which would otherwise take
    precedence and silently ignore the forbidden source.
    """
    if get_config().ALLOW_SERVER_PATHS:
        return
    supplied = [name for name, value in (("url", url), ("path", path)) if value]
    if supplied:
        raise _refuse_server_paths(f"storeMediaFile parameter(s) {', '.join(supplied)} are")


def reject_server_package_action(action: str) -> None:
    """Refuse package import/export, whose only input or output is a server path."""
    if not get_config().ALLOW_SERVER_PATHS:
        raise _refuse_server_paths(f"{action} is")
