"""Conformance helpers for third-party plugins (v8 item 4).

These helpers are intentionally small and dependency-free.  Use them in your
own test suite before registering a plugin in the ``cyrrus.plugins`` entry
point group::

    from cyrrus.testing import check_retriever, check_backend

    check_retriever(MyRetriever())
    check_backend(MyBackend())

``check_backend`` runs the async lifecycle on a temporary session id and
removes the session afterwards.  Use ``check_backend_async`` when already
inside an event loop.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Iterable

from .backend import MemoryBackend


def check_retriever(retriever: Any) -> None:
    """Assert that *retriever* implements the :class:`cyrrus.plugins.Retriever`
    contract.

    Checks the returned shape ``(score, keyword, value, tokens)``, that scores
    are numeric and sorted descending, that ``limit`` is respected and that
    rows at or below ``score_threshold`` are excluded.  Raises
    ``AssertionError`` with a readable message on the first violation.
    """
    assert callable(getattr(retriever, "rank", None)), (
        "retriever must define rank(facts, query, limit=..., score_threshold=...)"
    )

    facts = [
        ("check_location", "I live in Lisbon", 5),
        ("check_note", "unrelated note", 2),
    ]
    ranked = retriever.rank(
        facts, "where do I live", limit=2, score_threshold=0.0
    )
    assert isinstance(ranked, list), "rank() must return a list"
    assert len(ranked) <= 2, "rank() returned more than limit rows"
    previous = None
    for row in ranked:
        assert isinstance(row, tuple), "rank() rows must be tuples"
        assert len(row) == 4, (
            "rank() rows must be (score, keyword, value, tokens), got %r" % (row,)
        )
        score, keyword, value, tokens = row
        assert isinstance(score, (int, float)), "score must be numeric"
        assert isinstance(keyword, str), "keyword must be a string"
        assert isinstance(value, str), "value must be a string"
        assert isinstance(tokens, int), "tokens must be an int"
        assert score > 0.0, "rank() must not return rows at or below threshold"
        if previous is not None:
            assert score <= previous, "rank() rows must be sorted by score desc"
        previous = score


async def check_backend_async(backend: Any) -> None:
    """Async version of :func:`check_backend`."""
    assert isinstance(backend, MemoryBackend), (
        "backend must subclass cyrrus.backend.MemoryBackend"
    )

    session_id = "__cyrrus_conformance_%s__" % uuid.uuid4().hex
    await backend.init_db()
    try:
        await backend.upsert(
            session_id,
            "conformance_key",
            "conformance value",
            2,
            None,
            2000,
        )
        rows = await backend.retrieve_current(session_id, limit=10)
        assert any(
            row[0] == "conformance_key" for row in rows
        ), "retrieve_current() did not return the upserted fact"

        retrieve_ranked = getattr(backend, "retrieve_ranked", None)
        if callable(retrieve_ranked):
            result = await retrieve_ranked(
                session_id, "conformance", limit=3
            )
            assert isinstance(result, tuple) and len(result) == 2, (
                "retrieve_ranked() must return (ranked, dropped)"
            )
            ranked, dropped = result
            assert isinstance(ranked, list), "retrieve_ranked()[0] must be a list"
            assert isinstance(dropped, list), "retrieve_ranked()[1] must be a list"
            for row in ranked:
                assert isinstance(row, tuple) and len(row) == 4, (
                    "retrieve_ranked() rows must be "
                    "(score, keyword, value, tokens)"
                )

        history = await backend.get_fact_history(session_id, "conformance_key")
        assert isinstance(history, list), "get_fact_history() must return a list"
        exported = await backend.export_facts(session_id)
        assert isinstance(exported, list), "export_facts() must return a list"
        listed = await backend.list_sessions()
        assert isinstance(listed, list), "list_sessions() must return a list"
    finally:
        await backend.forget_session(session_id)


def check_backend(backend: Any) -> None:
    """Synchronous wrapper for :func:`check_backend_async`."""
    asyncio.run(check_backend_async(backend))
