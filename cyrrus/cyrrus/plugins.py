"""Small plugin slots and entry-point discovery (v8 item 4).

Three hook points exist in the core:

* ``Retriever`` - rank a sequence of facts against a query. The default is
  :class:`BM25Retriever`, which wraps :func:`cyrrus.bm25.bm25_rank_facts`.
* ``Packer`` - pack slides into a token budget. The default is
  :class:`cyrrus.knapsack.TokenKnapsack`, which already matches this protocol.
* storage backend - :class:`cyrrus.backend.MemoryBackend`. The default is
  :class:`cyrrus.sqlite_backend.SQLiteBackend`.

Third-party implementations are discovered through the ``cyrrus.plugins``
``importlib.metadata`` entry-point group. An entry point may load:

* an already-constructed object implementing the protocol,
* a class, or
* a factory accepting a single ``config`` mapping.

Selection is configuration driven, for example::

    {
      "plugins": {
        "retriever": "my_retriever",
        "packer": "my_packer",
        "backend": "my_backend"
      }
    }

Names are resolved lazily. No entry points and no extra dependencies are
needed for the built-in defaults: ``bm25``, ``token_knapsack`` and ``sqlite``.
"""
from __future__ import annotations

import inspect
import logging
from importlib import metadata
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

log = logging.getLogger("cyrrus.plugins")

PLUGIN_GROUP = "cyrrus.plugins"
PLUGIN_KINDS = ("retriever", "packer", "backend")

Fact = Tuple[str, str, int]
RankedFact = Tuple[float, str, str, int]


@runtime_checkable
class Retriever(Protocol):
    """Rank stored facts for a query.

    ``facts`` contains ``(keyword, value, tokens)`` tuples. Implementations
    return ``(score, keyword, value, tokens)`` tuples sorted by descending
    score, at most ``limit`` rows, excluding scores at or below
    ``score_threshold``. Extra keyword arguments are allowed so the core can
    pass retrieval tuning knobs without breaking older plugins.
    """

    def rank(
        self,
        facts: Sequence[Fact],
        query: str,
        limit: int = 3,
        score_threshold: float = 0.0,
        **kwargs: Any,
    ) -> List[RankedFact]:
        ...


@runtime_checkable
class Packer(Protocol):
    """Pack candidate slides into a token budget."""

    def pack(self, candidates: List[Any], budget: int) -> List[Any]:
        ...


class BM25Retriever:
    """Default :class:`Retriever`: the core BM25 keyword ranker."""

    name = "bm25"

    def __init__(
        self,
        max_df_fraction: float = 0.5,
        remove_stopwords: bool = True,
    ):
        self.max_df_fraction = float(max_df_fraction)
        self.remove_stopwords = bool(remove_stopwords)

    def rank(
        self,
        facts: Sequence[Fact],
        query: str,
        limit: int = 3,
        score_threshold: float = 0.0,
        **kwargs: Any,
    ) -> List[RankedFact]:
        from .bm25 import bm25_rank_facts

        return bm25_rank_facts(
            facts,
            query,
            limit=limit,
            score_threshold=score_threshold,
            max_df_fraction=kwargs.get("max_df_fraction", self.max_df_fraction),
            remove_stopwords=kwargs.get(
                "remove_stopwords", self.remove_stopwords
            ),
        )


def _iter_entry_points(group: str = PLUGIN_GROUP):
    """Return entry points for *group* across py3.9/py3.10+ metadata APIs."""
    try:
        eps = metadata.entry_points(group=group)
    except TypeError:  # py3.9 returns a mapping instead of accepting group=
        eps = metadata.entry_points()
        if hasattr(eps, "select"):
            eps = eps.select(group=group)
        elif isinstance(eps, dict):
            eps = eps.get(group, [])
    return list(eps)


def list_plugins(group: str = PLUGIN_GROUP) -> List[str]:
    """Return built-in and entry-point plugin names, sorted and de-duplicated."""
    names = {"bm25", "hybrid", "token_knapsack", "sqlite"}
    for ep in _iter_entry_points(group):
        names.add(ep.name)
    return sorted(names)


def _construct(factory: Any, config: Dict[str, Any]) -> Any:
    """Instantiate a plugin class/factory without imposing a base class."""
    if not config:
        return factory()
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return factory()
    if "config" in params:
        return factory(config)
    kwargs = {key: value for key, value in config.items() if key in params}
    if kwargs:
        return factory(**kwargs)
    return factory()


def _instantiate(loaded: Any, config: Dict[str, Any]) -> Any:
    if not isinstance(loaded, type):
        if any(hasattr(loaded, attr) for attr in ("rank", "pack", "init_db")):
            return loaded
        if callable(loaded):
            return _construct(loaded, config)
        return loaded
    return _construct(loaded, config)


def _check_contract(kind: str, plugin: Any) -> None:
    from .backend import MemoryBackend

    if kind == "retriever":
        if not isinstance(plugin, Retriever):
            raise TypeError(
                "Retriever plugin %r does not implement rank()" % (plugin,)
            )
    elif kind == "packer":
        if not isinstance(plugin, Packer):
            raise TypeError(
                "Packer plugin %r does not implement pack()" % (plugin,)
            )
    elif kind == "backend":
        if not isinstance(plugin, MemoryBackend):
            raise TypeError(
                "Backend plugin %r must subclass MemoryBackend" % (plugin,)
            )


def _builtin(kind: str, name: str, config: Dict[str, Any]) -> Optional[Any]:
    if kind == "retriever" and name == "bm25":
        return BM25Retriever()
    if kind == "retriever" and name == "hybrid":
        from .hybrid import HybridRetriever

        return HybridRetriever.from_config(config)
    if kind == "packer" and name == "token_knapsack":
        from .knapsack import TokenKnapsack

        return TokenKnapsack()
    if kind == "backend" and name == "sqlite":
        from .sqlite_backend import SQLiteBackend

        db_path = config.get("db_path")
        return SQLiteBackend(db_path) if db_path else SQLiteBackend()
    return None


def resolve_plugin(
    kind: str,
    name: str,
    config: Optional[Dict[str, Any]] = None,
) -> Any:
    """Resolve one plugin by kind and name.

    ``kind`` is one of ``retriever``, ``packer`` or ``backend``. Built-ins are
    resolved first; otherwise the ``cyrrus.plugins`` entry point with the same
    name is loaded. Raises ``LookupError`` for an unknown name and ``TypeError``
    when the loaded object does not implement the slot.
    """
    if kind not in PLUGIN_KINDS:
        raise ValueError(
            "plugin kind must be one of %s, got %r"
            % (", ".join(PLUGIN_KINDS), kind)
        )
    if not isinstance(name, str) or not name.strip():
        raise ValueError("plugin name must be a non-empty string")
    config = dict(config or {})

    builtin = _builtin(kind, name, config)
    if builtin is not None:
        return builtin

    for ep in _iter_entry_points():
        if ep.name == name:
            plugin = _instantiate(ep.load(), config)
            _check_contract(kind, plugin)
            log.info(
                "Loaded %s plugin %r from %s",
                kind,
                name,
                getattr(ep, "value", "<entry point>"),
            )
            return plugin

    raise LookupError(
        "Unknown %s plugin %r. Available: %s"
        % (kind, name, ", ".join(list_plugins()))
    )
