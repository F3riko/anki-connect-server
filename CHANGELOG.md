# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0+safe.1] - 2026-10-17

### Fixed
- **Fail-Closed Safe Sync Policy**:
  - `sync_collection` now explicitly calls Anki backend with `sync_media=False` to prevent background media sync from racing collection resolution.
  - Fail-closed handling for all full sync conditions: `FULL_SYNC`, `FULL_DOWNLOAD`, and `FULL_UPLOAD` now raise a clear `SyncError` indicating that explicit human direction is required; automatic full download/upload and collection replacement are completely disabled by policy to prevent accidental data loss.
  - Direct `_full_download` helper is disabled by safety policy.
  - Explicit media sync lifecycle: background media sync (`sync_media`) is only initiated after collection sync successfully resolves with `NORMAL_SYNC` or `NO_CHANGES`. The server awaits inactive media status before refreshing and reopening the collection handle.
  - Strict media status checking: `_wait_for_media` raises `SyncError` on status polling exceptions (fixing upstream bug where errors were caught and treated as success) and checks backend media error fields.
  - Bounded abort and idle verification: timeouts or media errors trigger `abort_media_sync()` and boundedly await inactive status before any collection close/reopen. If idle cannot be confirmed, the collection is NOT closed or reopened (fail-closed).
  - Active-media preflight: subsequent sync attempts reject immediately if media is still active or unconfirmed.

## [0.4.0] - 2026-09-27

### Added
- `storeMediaFile` accepts `url` (server-side download, httpx with redirects
  and a 30s timeout) and `path` (server-side file) in addition to base64
  `data`; precedence `data` > `url` > `path`, mirroring upstream Anki-Connect.
  Missing source, unreachable URL, or unreadable path raise client-facing
  errors. The MCP `store_media_file` tool exposes the same options.

### Fixed
- Return the bare result with no `{result, error}` envelope for requests at
  version ≤4 (missing `version` now defaults to 4), matching the AnkiConnect
  spec used by legacy clients such as Yomitan.

## [0.3.1] - 2026-09-27

### Fixed
- `retrieveMediaFile` / `deleteMediaFile`: replace the removed
  `MediaManager.read_data` (anki 26.x) with a direct disk read of the media
  dir, and route deletions through `trash_files` as upstream Anki-Connect
  does (`1fd7779`).
- Sanitize media filenames (basename + NFC + illegal-char stripping) for
  retrieve/delete, closing a path-traversal vector in `retrieveMediaFile`
  (`1fd7779`).

## [0.3.0] - 2026-08-05

### Added
- MCP server instructions and per-tool safety annotations (read-only,
  idempotent, additive, destructive) so AI assistants can reason about
  mutating operations (`642f9dc`).
- Serve the AnkiConnect API at `POST /` in addition to `/api` (`6a2a5f7`).

### Changed
- Resolve sync requirements via `SyncCollectionResponse` enums and return a
  structured `SyncResult` describing the collection outcome, media counters,
  and any server message (`98a949b`).
- Wire Pydantic models / TypedDict input shapes into every handler with a
  registry-based dispatch (`95021d1`, `c64d9f9`, `723e44b`).
- Route blocking `col.*` calls through `asyncio.to_thread` so the FastAPI
  event loop stays responsive (`5ec1a4d`).
- Remove the global wrapper singleton in favor of `app.state` for FastAPI
  (`6a47cf9`).
- Make `cli.main` testable via an `argv` parameter (`a201a8b`).

### Fixed
- `updateNoteFields` silently succeeded for missing/nonexistent note ids;
  it now raises a clear error (`5d2a021`).
- Distinguish validation errors (HTTP 200 with `error`) from server errors
  (HTTP 500) in the API layer (`11c0437`).
- Dockerfile `CMD` referenced a non-existent `server` subcommand (`bcf8753`).
- Validate `COLLECTION_PATH` instead of failing opaquely inside
  `Collection()` (`2a57e68`).
- `findNotes` / `findCards` with an empty query returned the entire
  collection (`ff1a2ef`).
- `multi` aborted the whole batch when one sub-action failed (`c644819`).
- `suspend` returned `False` when no cards were newly suspended (`20447f5`).
- `getIntervals` `last_interval` reported the lapse count instead of the
  previous interval (`bea9ec5`).
- `areSuspended` crashed on missing card ids (`4f66f16`).
- Restore the collection safely when a sync fails (`5944473`).
- Actually wait for media sync completion in `syncMedia` (`7e97720`).
- Reject concurrent AnkiWeb syncs with a `_sync_lock` (`3f22ed6`).
- Handle the `required=2` sync action (`90bf4fa`).

### Tests
- Cover `model_fields_on_templates`, `syncStatus`, and `app_lifespan`
  (`5a57e6a`).
- Cover `collection_generation` increments across sync paths (`34aaa19`).
- Isolate the test working directory to prevent `.env` credential leak
  (`743a0d0`).
- Use `monkeypatch` instead of mutating global config (`b173322`).

### CI / Tooling
- Add quality gates (ruff + pyright), strict typing, and tightened
  dependency floors (`d5d700d`, `c3abd20`).
- Separate Docker build and description update jobs (`b5cd41a`).

## [0.2.0] - 2026-04-23

### Added
- Unified CLI with `api` and `mcp` subcommands (`69b5f10`).
- Dockerfile for containerized deployment (`e66e89f`).
- Mount FastMCP to FastAPI at the `/mcp` endpoint (`d7740bd`).
- Move source files to the `src/anki_connect_server` package layout
  (`9ed6478`).
- Add credentials to all `uvx` usage examples (`9ef2005`, `1b04bd8`).

### Changed
- Move dev dependencies to `[dependency-groups]` (`10fd09b`).

### Fixed
- Rename `main` to `run` for the MCP server CLI entry point (`7b1f0d0`).
- Add a `run` function alias for the MCP server CLI entry point (`d090a88`).

## [0.1.3] - 2026-03-25

### Fixed
- CLI entry point fixes for PyPI release.

## [0.1.2] - 2026-03-24

### Fixed
- Rename `main` to `run` for the MCP server CLI entry point (`7b1f0d0`).
- Add a `run` function alias for the MCP server CLI entry point (`d090a88`).

## [0.1.1] - 2026-03-20

### Fixed
- Initial CLI entry point fixes.

## [0.1.0] - 2026-03-15

### Added
- Initial release of the headless AnkiConnect-compatible REST API server
  with AnkiWeb sync support and MCP server integration.