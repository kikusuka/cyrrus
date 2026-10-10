"""
Simple chat adapters for cyrrus.

Provides: make_chat(projector, llm_call) -> async chat(session_id, user_text)
which composes projector.process() with the raw LLM call, persists the
assistant reply into the projector's history so memory and extraction keep
working, and returns the reply text.

Typical use is a Discord/Slack bot where the caller wants one function per
user message. See README for a 15-line Discord example.
"""
from __future__ import annotations

from typing import Callable, Awaitable, Optional


def make_chat(
    projector: object,
    llm_call: Optional[Callable[[list], Awaitable[str]]] = None,
) -> Callable[[str, str], Awaitable[str]]:
    """
    Build a chat(session_id, user_text) coroutine from a Projector.

    Args:
        projector: A cyrrus.Projector instance. It should already have an
                   internal llm_call configured via its constructor; if
                   *llm_call* is also provided here, it will replace the
                   projector's internal one for subsequent calls.
        llm_call: Optional replacement for the projector's llm_call. When
                  passed, projector.llm_call is reassigned so that
                  projector.process() will use the new provider.

    Returns:
        async def chat(session_id: str, user_text: str) -> str:
            1. Call projector.process(user_text, session_id=session_id)
               (this handles routing / memory / history / tool execution
               and already records the assistant reply internally).
            2. Return the reply text.
    """
    if llm_call is not None:
        projector.llm_call = llm_call

    async def chat(session_id: str, user_text: str) -> str:
        """Process one turn and return the assistant reply."""
        return await projector.process(user_text, session_id=session_id)

    return chat


__all__ = ["make_chat"]
