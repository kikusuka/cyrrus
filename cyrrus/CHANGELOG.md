# Changelog

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
