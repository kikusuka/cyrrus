from dataclasses import replace
from typing import List, Dict, Optional
from .data import Slide


class SlideTray:
    """
    Tracks which slides are active vs fading into ghost status.

    Active slides show their full content. Ghosts show a fading note
    so the model knows the topic was recently discussed. Both age out
    after a configurable number of turns.

    Per-slide TTL: set active_turns on a slide to override the global
    max_active_turns. Useful when a coding session should stay active
    for 8 turns but a greeting should fade after 1.
    """

    def __init__(
        self,
        max_active_turns: int = 2,
        max_ghost_slides: int = 5,
        max_ghost_turns: int = 2,
    ):
        if max_active_turns < 1:
            raise ValueError("max_active_turns must be at least 1")
        if max_ghost_slides < 0:
            raise ValueError("max_ghost_slides must be non-negative")
        if max_ghost_turns < 0:
            raise ValueError("max_ghost_turns must be non-negative")
        self.active: List[Slide] = []
        self.ghosts: List[Slide] = []
        self.turn_counters: Dict[str, int] = {}
        self.ghost_ages: Dict[str, int] = {}
        self.max_turns = max_active_turns
        self.max_ghost_slides = max_ghost_slides
        self.max_ghost_turns = max_ghost_turns

    def _ttl(self, slide: Slide) -> int:
        """Per-slide TTL if set, otherwise global default."""
        return slide.active_turns if slide.active_turns is not None else self.max_turns

    def update(self, new_slides: List[Slide]):
        surviving = []
        newly_ghosted = set()
        for s in self.active:
            self.turn_counters[s.id] = self.turn_counters.get(s.id, 0) + 1
            if self.turn_counters[s.id] > self._ttl(s):
                self.ghosts.append(replace(s, is_ghost=True))
                self.ghost_ages[s.id] = 0
                newly_ghosted.add(s.id)
            else:
                surviving.append(s)

        existing_ids = {s.id for s in surviving}
        for s in new_slides:
            if s.id not in existing_ids:
                surviving.append(s)
            # Reset counter for any slide routed this turn — active usage
            # means the TTL clock restarts, not continues ticking.
            self.turn_counters[s.id] = 0
            self.ghost_ages.pop(s.id, None)

        self.active = surviving
        # Clear any ghost that just got re-triggered — it's active again.
        active_ids = {s.id for s in self.active}
        retained = [s for s in self.ghosts if s.id not in active_ids]
        surviving_ghosts = []
        for s in retained:
            if s.id not in newly_ghosted:
                self.ghost_ages[s.id] = self.ghost_ages.get(s.id, 0) + 1
            if self.ghost_ages[s.id] <= self.max_ghost_turns:
                surviving_ghosts.append(s)
            else:
                self.ghost_ages.pop(s.id, None)

        self.ghosts = (
            surviving_ghosts[-self.max_ghost_slides:]
            if self.max_ghost_slides else []
        )
        retained_ids = {s.id for s in self.ghosts}
        for s in surviving_ghosts:
            if s.id not in retained_ids:
                self.ghost_ages.pop(s.id, None)

    def all_slides(self) -> List[Slide]:
        return self.active + self.ghosts
