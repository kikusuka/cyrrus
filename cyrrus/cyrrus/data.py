from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Slide:
    id: str
    type: str        # 'lamp', 'lens', 'tool', 'memory', 'data'
    content: str
    tokens: int
    priority: int
    is_ghost: bool = False
    handler: Optional[str] = None
    active_turns: Optional[int] = None   # per-slide TTL; falls back to global max_active_turns
    tool_estimate_tokens: int = 150      # estimated tool output size for budget planning
