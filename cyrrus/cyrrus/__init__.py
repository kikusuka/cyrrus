from .projector import Projector, SessionLocks
from .data import Slide
from .memory import MemoryVault
from .router import IntentRouter
from .tray import SlideTray
from .knapsack import TokenKnapsack
from .extractor import (
    configure_fact_extractor,
    extract_facts,
    get_fact_extractor_tier,
)
from .providers import StreamChunk, openai_compatible
from . import providers
from .backend import MemoryBackend
from .sqlite_backend import SQLiteBackend, get_backend, close_backend
from .renderers import compact

__version__ = "0.3.0b3"

def estimate_tokens(text: str) -> int:
    """Rough token count. Useful for setting 'tokens' in config manually."""
    return max(1, len(text.split()))

__all__ = [
    "Projector",
    "SessionLocks",
    "Slide",
    "MemoryVault",
    "IntentRouter",
    "SlideTray",
    "TokenKnapsack",
    "extract_facts",
    "configure_fact_extractor",
    "get_fact_extractor_tier",
    "StreamChunk",
    "openai_compatible",
    "providers",
    "MemoryBackend",
    "SQLiteBackend",
    "get_backend",
    "close_backend",
    "estimate_tokens",
    "compact",
    "__version__",
]
