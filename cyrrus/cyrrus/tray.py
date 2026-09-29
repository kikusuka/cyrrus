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

    def __init__(self, max_active_turns: int = 2, max_ghost_slides: int = 5):
        if max_active_turns < 1:
            raise ValueError("max_active_turns must be at least 1")
        if max_ghost_slides < 0:
            raise ValueError("max_ghost_slides must be non-negative")
        self.active: List[Slide] = []
        self.ghosts: List[Slide] = []
        self.turn_counters: Dict[str, int] = {}
        self.ghost_ages: Dict[str, int] = {}  # Track how many turns as ghost
        self.max_turns = max_active_turns
        self.max_ghost_slides = max_ghost_slides

    def _ttl(self, slide: Slide) -> int:
        """Per-slide TTL if set, otherwise global default."""
        return slide.active_turns if slide.active_turns is not None else self.max_turns

    def update(self, new_slides: List[Slide]):
        surviving = []
        for s in self.active:
            self.turn_counters[s.id] = self.turn_counters.get(s.id, 0) + 1
            if self.turn_counters[s.id] > self._ttl(s):
                self.ghosts.append(replace(s, is_ghost=True))
                # Initialize ghost age when slide becomes a ghost
                self.ghost_ages[s.id] = 0
            else:
                surviving.append(s)

        existing_ids = {s.id for s in surviving}
        for s in new_slides:
            if s.id not in existing_ids:
                surviving.append(s)
            # Reset counter for any slide routed this turn — active usage
            # means the TTL clock restarts, not continues ticking.
            self.turn_counters[s.id] = 0
            # If slide was a ghost, it's now active again - clean up ghost state
            if s.id in self.ghost_ages:
                del self.ghost_ages[s.id]

        self.active = surviving
        # Clear any ghost that just got re-triggered — it's active again.
        active_ids = {s.id for s in self.active}
        retained = [s for s in self.ghosts if s.id not in active_ids]
        
        # Age out ghosts: increment ghost age and remove expired ghosts
        # Ghosts expire after max_turns as a ghost (prevents memory leak)
        surviving_ghosts = []
        for s in retained:
            self.ghost_ages[s.id] = self.ghost_ages.get(s.id, 0) + 1
            if self.ghost_ages[s.id] <= self.max_turns:
                surviving_ghosts.append(s)
            else:
                # Ghost has expired, clean up
                del self.ghost_ages[s.id]
        
        # Apply max_ghost_slides cap to aged ghosts
        if self.max_ghost_slides:
            self.ghosts = surviving_ghosts[-self.max_ghost_slides:]
        else:
            self.ghosts = []

    def all_slides(self) -> List[Slide]:
        return self.active + self.ghosts
