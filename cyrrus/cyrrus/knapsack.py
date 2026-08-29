import logging

log = logging.getLogger("slides.knapsack")


class TokenKnapsack:
    @staticmethod
    def pack(candidates: list, budget: int) -> list:
        """Fits as many slides as possible into the token budget,
        prioritizing by value density (priority / tokens)."""
        ranked = sorted(candidates, key=lambda s: s.priority / max(s.tokens, 1), reverse=True)
        packed = []
        used = 0
        for slide in ranked:
            if used + slide.tokens <= budget:
                packed.append(slide)
                used += slide.tokens
            else:
                log.debug("Dropped '%s' (%d tokens) — over budget.", slide.id, slide.tokens)
        return packed
