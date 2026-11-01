# Changelog

## Unreleased

### Changed
- Dev utilities moved from ``cyrrus/tools`` to ``cyrrus/devtools`` so the dev folder no longer shadows the ``cyrrus.tools`` module.

### Added
- Services registry with data-driven service definitions (ollama, lmstudio, llama.cpp, openai, mistral, groq, openrouter, anthropic, custom)
- Configuration system with project and user settings files (`cyrrus.config.json`)
- Precedence: CLI flags > environment variables > project file > user file > defaults
- `.env` file support with automatic `.gitignore` management
- Tools layer with plain functions for models, connection, doctor, memory, sessions, routing
- Real memory and sessions tools layer:
  - `memory_list(session, include_superseded=False)` backed by `export_facts`
  - `memory_search(session, query, limit)` via BM25 / hybrid retrieval returning key, value, and score
  - `memory_forget(session, key)` via `forget_fact`
  - `memory_forget_all(session)` via `forget_session`
  - `memory_export(session, path)` writing JSON
  - `memory_import(session, path)` validating all rows before upsert
  - `sessions()` listing session IDs with active fact counts
  - `MemoryBackend.list_sessions()` default method and `SQLiteBackend` implementation
- CLI commands: `doctor`, `connect`, `services`, `models`, `route`, `memory`, `sessions`, `config`
- Global CLI flags: `--config`, `--db`, `--session`, `--json`, `--no-color`, `--version`, `--yes`
- Secret redaction in configuration display
- Service detection for local services with configurable timeout
- Diagnostic checks via `cyrrus doctor`
- Memory operations: list, search, forget, forget-all, export, import
- Context routing dry run via `cyrrus route`
- Terminal UI layer: capability detection (`cyrrus.ui.caps`), theme/palette
  with ASCII fallbacks (`cyrrus.ui.theme`), generated logo art tiers
  (`cyrrus.ui.art`), and an intro animation (`cyrrus.ui.anim`)
- New CLI commands `cyrrus intro` and `cyrrus logo` plus the `--no-anim`
  flag; `cyrrus ui` respects `ui.animation`/`ui.onboarded`, TTY, CI and
  `CYRRUS_NO_ANIM`, and never animates over stdout (protocol/non-interactive
  mode).

### Changed
- Extended CLI with new commands while preserving existing `init` functionality
- Added `cyrrus/__main__.py` for module execution
- Replaced memory and session tool placeholders with real implementations

## 0.3.0b5

### Fixed
- Python 3.9: asyncio locks (SessionLocks._meta, SQLiteBackend._init_lock) are
  now created lazily inside async methods, so Projector can be built outside
  a running event loop.
- Extractor values stop at conjunctions: "my name is Alice and I live in Lisbon"
  now stores the name as "Alice" instead of "Alice and".
- Compact renderer no longer shows fact values as keys and keeps the base prompt.

### Added
- `wait_for_extraction` option on `Projector.process()` and `aprocess_stream()`.
- `embedding_min_score` (default 0.68) and hybrid embedding retrieval:
  keyword/alias matches first, then embedding-only matches above threshold,
  de-duplicated by fact id and capped at the limit.
- `forget_fact(session_id, key)`, `forget_session(session_id)` and
  `export_facts(session_id, include_superseded=False)` on Projector,
  MemoryVault, and SQLiteBackend; custom backends get NotImplementedError
  defaults.
- `process_sync()`, `flush_sync()` and `close_sync()`: a synchronous wrapper
  running on a private background event loop thread.

### Changed
- Default database location is now a per-user folder (Windows: %LOCALAPPDATA%,
  macOS/Linux: $XDG_DATA_HOME or ~/.local/share). Set `memory_db_path` or
  `CYRRUS_DB_PATH` to keep the old location, e.g. `memory_db_path="slides_memory.db"`.
- Default and compact renderers now show readable fact labels, so default
  system-message text changed.

## 0.3.0b4

### Added
- Pluggable `tokenizer` (object with `.encode` or a `str -> int` callable) used for all token budgeting.
- Pluggable `renderer` for the system message, plus the built-in `cyrrus.renderers.compact`.
- `projector.last_trace`: a decision trace showing routed slides, ghosts, injected facts, and dropped items with reasons ("over token budget", "over fact cap", "below threshold", "ghost expired").
- Pluggable `fact_extractor` (sync or async; dict or list of pairs) with `extractor_mode="replace"|"merge"`, `extractor_timeout`, and fallback to the built-in extractor on failure.
- Pluggable `history_summarizer` with `summarizer_timeout` and fallback to the built-in compaction.
- `cyrrus.openai_compatible(base_url, model, api_key=None, timeout=120.0)`: provider for llama.cpp, vLLM, LM Studio, Ollama's /v1 and similar servers, with streaming.
- LICENSE file now ships in the wheel and sdist; CI runs on Python 3.9 to 3.13.

### Changed
- Semantic (embedding) retrieval is now opt-in: pass `embedder=` or `embedding_model=`. Previously it loaded automatically when `fastembed` was installed, which could change retrieval results unexpectedly. The default is keyword (BM25) only.
- Trace labels: slides evicted for lack of token budget are now reported as "over token budget"; "ghost expired" is used only when a ghost ages out.
- License metadata is now the SPDX string `AGPL-3.0-only`.

### Notes
- `process()` extracts facts in the background. In short scripts, call `await projector.flush()` (or use `async with Projector(...)`) before exiting, otherwise the last turn's facts can be lost.

## 0.3.0b3

### Added
- Input validation: `session_id` and fact keys must be non-empty and at most 256 characters
  (`ValueError` otherwise); fact values are truncated at 2000 characters.
- Optional `max_facts_per_session` retention cap; when set, the oldest superseded facts are
  evicted first, then the oldest active facts.

### Changed
- `max_facts_per_session` now defaults to unlimited (previously 500).
  Set it explicitly if you rely on automatic pruning.
- Default fact value length limit raised from 500 to 2000 characters.

## 0.3.0b2

### Fixed
- Ghost slides now expire after exactly `max_ghost_turns` ghost turns (previously one turn too long).
  Behavior change: if you tuned `max_ghost_turns`, expect ghosts to leave one turn sooner.
- Memory facts are now retrieved fresh each turn and no longer persist in the slide tray,
  so irrelevant facts stop leaking into unrelated queries.
- Background fact extraction is awaited on shutdown: new `await projector.flush()`,
  `await projector.aclose()` and `async with Projector(...)`.
- Ollama provider no longer blocks the event loop; configurable `timeout`.

### Added
- `max_memory_facts` (default 5) and `max_memory_tokens` to cap injected memory.
- Newer facts supersede older ones; richer built-in extractor ("I moved to X", "I like X", ...).
- Question-style memory retrieval ("where do I live?") via key aliases.
- `cyrrus.adapters.make_chat(projector, llm_call)`: a simple chat wrapper with a Discord example in the README.
