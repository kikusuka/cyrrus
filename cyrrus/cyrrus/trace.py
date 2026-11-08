"""Bounded, prompt-safe retrieval traces.

A :class:`Candidate` is one item retrieval considered for the context: a
stored fact (``source="fact"``) or a routed slide (``source="slide"``).  The
per-turn :class:`Trace` records the score and the include/drop decision for
each candidate.

Fact values are prompt text.  They are only copied into a trace when the
trace was created with ``include_values=True`` (the ``memory.trace_values``
config setting); otherwise only the fact key is retained.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# A trace is an observability aid, not a second copy of the corpus.  Keep the
# ranked tail bounded just like the existing dropped-fact list.
TRACE_CANDIDATE_CAP = 100


@dataclass
class Candidate:
    source: str
    id: str
    score: float
    included: bool
    reason: Optional[str] = None
    dropped_reason: Optional[str] = None
    value: Optional[str] = None

    def to_dict(self, include_value: bool = False) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "source": self.source,
            "id": self.id,
            "key": self.id,
            "score": self.score,
            "included": self.included,
        }
        if self.included:
            item["reason"] = self.reason or "included"
        else:
            item["dropped_reason"] = self.dropped_reason or "dropped"
        if include_value and self.value is not None:
            item["value"] = self.value
        return item


@dataclass
class Trace:
    session_id: Optional[str] = None
    include_values: bool = False
    candidates: List[Candidate] = field(default_factory=list)

    def add_fact(
        self,
        key: str,
        score: float,
        value: Optional[str],
        included: bool,
        reason: Optional[str] = None,
        dropped_reason: Optional[str] = None,
    ) -> Candidate:
        candidate = Candidate(
            source="fact",
            id=key,
            score=float(score),
            included=bool(included),
            reason=reason,
            dropped_reason=dropped_reason,
            value=value if self.include_values else None,
        )
        self.candidates.append(candidate)
        return candidate

    def add_slide(
        self,
        slide_id: str,
        score: float,
        included: bool,
        reason: Optional[str] = None,
        dropped_reason: Optional[str] = None,
    ) -> Candidate:
        candidate = Candidate(
            source="slide",
            id=slide_id,
            score=float(score),
            included=bool(included),
            reason=reason,
            dropped_reason=dropped_reason,
        )
        self.candidates.append(candidate)
        return candidate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "candidates": [c.to_dict(self.include_values) for c in self.candidates],
        }
