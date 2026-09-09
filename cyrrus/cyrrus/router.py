import re
import logging
from typing import Dict, Set
from .data import Slide
from .negation import is_negated
from .stemmer import PorterStemmer, normalize_token, SYNONYMS

log = logging.getLogger("cyrrus.router")


class IntentRouter:
    """
    Keyword/regex router — the zero-dependency default.
    Matches trigger words from your config, word-boundary and negation aware.

    The `examples` field in slide config is meaningful here too: if a slide
    has examples but no triggers, it won't match via keywords. Install
    cyrrus[embeddings] and use EmbeddingRouter to match against examples
    semantically. IntentRouter focuses on what it can do reliably: exact
    trigger word matching.
    """

    def __init__(self, slides_config: dict, negation_aware: bool = True):
        self.slides = slides_config
        self.negation_aware = negation_aware
        self._keyword_map: Dict[str, Set[str]] = {}
        self._stemmer = PorterStemmer()
        self._build_index()

    def _build_index(self):
        for slide_id, data in self.slides.items():
            if slide_id == "core_lamp" or slide_id.startswith("_"):
                continue
            for trigger in data.get("triggers", []):
                # Normalize trigger: stem and add all synonym variants
                normalized_forms = normalize_token(trigger, self._stemmer)
                for form in normalized_forms:
                    self._keyword_map.setdefault(form, set()).add(slide_id)

    def _make_slide(self, sid: str) -> Slide:
        data = self.slides[sid]
        return Slide(
            id=sid,
            type=data.get("type", "data"),
            content=data.get("content", ""),
            tokens=data.get("tokens", 10),
            priority=data.get("priority", 500),
            handler=data.get("handler"),
            active_turns=data.get("active_turns"),
            tool_estimate_tokens=data.get("tool_estimate_tokens", 150),
        )

    async def route(self, user_input: str) -> tuple:
        lower = user_input.lower()
        matched = set()
        negated = set()

        # Tokenize input and normalize each token
        tokens = re.findall(r'\b\w+\b', lower)
        
        for token in tokens:
            # Normalize token: stem and expand synonyms
            normalized_forms = normalize_token(token, self._stemmer)
            
            for form in normalized_forms:
                if form in self._keyword_map:
                    for sid in self._keyword_map[form]:
                        # Find the original match position for negation checking
                        for m in re.finditer(rf"\b{re.escape(token)}\b", lower):
                            if self.negation_aware and is_negated(lower, m.start()):
                                negated.add(sid)
                            else:
                                matched.add(sid)

        slides = [self._make_slide(sid) for sid in matched]
        slides.sort(key=lambda s: s.priority, reverse=True)
        return slides, (negated - matched)
