from .projector import Projector
from .data import Slide
from .memory import MemoryVault
from .router import IntentRouter
from .tray import SlideTray
from .knapsack import TokenKnapsack
from .extractor import extract_facts
from . import providers

__version__ = "0.1.0"

def estimate_tokens(text: str) -> int:
    """Rough token count. Useful for setting 'tokens' in config manually."""
    return max(1, len(text.split()))

__all__ = [
    "Projector",
    "Slide",
    "MemoryVault",
    "IntentRouter",
    "SlideTray",
    "TokenKnapsack",
    "extract_facts",
    "providers",
    "estimate_tokens",
    "__version__",
]
