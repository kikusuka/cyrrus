"""
Tests for EmbeddingRouter that don't require fastembed/network:
- graceful fallback when the dependency isn't installed (or fails to load)
- the hybrid pass never regresses what keyword matching already got right
- negation still works fully on the keyword-matched path

The actual embedding-similarity pass (paraphrase matching) can only be
verified with fastembed installed and a real model downloaded - that
needs Colab (real network). Run this file locally/here; run
test_v1.py + a real-model check in Colab for full coverage.
"""
import asyncio
import json
import os
import sys
from cyrrus.embedding_router import EmbeddingRouter

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slides.json")

FAILED = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


async def test_falls_back_without_fastembed():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    try:
        import fastembed  # noqa
        print("SKIPPED: fastembed IS installed here - this test needs it absent to be meaningful")
        return
    except ImportError:
        pass

    router = EmbeddingRouter(config)
    check("router falls back to keyword-only mode when fastembed isn't installed",
          router._model is None)

    slides, negated = await router.route("please search for cats")
    check("fallback mode still correctly routes a plain keyword match",
          any(s.id == "web_search" for s in slides))


async def test_hybrid_preserves_negation_on_keyword_path():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    router = EmbeddingRouter(config)  # will be in fallback mode here (no fastembed)

    slides, negated = await router.route("please don't search for cats, just guess")
    check("negation still works fully through the keyword-matching pass",
          not any(s.id == "web_search" for s in slides) and "web_search" in negated)


async def test_hybrid_never_loses_a_keyword_match():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    keyword_only_router = EmbeddingRouter(config)  # fallback mode, since no fastembed here
    slides, _ = await keyword_only_router.route("write a python script and search for cats")
    matched_ids = {s.id for s in slides}
    check("both keyword-triggered slides are present (hybrid didn't drop anything keyword matching found)",
          "code_lens" in matched_ids and "web_search" in matched_ids)


class FakeEmbedder:
    """Deterministic fake embedder for testing the RELATIVE decision
    rule (margin over runner-up, absolute floor, averaging across a
    slide's examples) without needing fastembed or a real model.
    vectors: dict mapping exact text -> a fixed vector. Any text not
    in the dict embeds to an all-zero vector (clearly non-matching)."""
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, texts):
        return [self.vectors.get(t, [0.0, 0.0, 0.0]) for t in texts]


def minimal_config():
    return {
        "core_lamp": {"content": "x", "tokens": 10, "priority": 1000},
        "slide_a": {"content": "A", "tokens": 10, "priority": 500,
                    "examples": ["example a1", "example a2"]},
        "slide_b": {"content": "B", "tokens": 10, "priority": 500,
                    "examples": ["example b1", "example b2"]},
    }


async def test_clear_winner_with_margin_matches():
    config = minimal_config()
    vectors = {
        "example a1": [1.0, 0.0, 0.0],
        "example a2": [1.0, 0.0, 0.0],
        "example b1": [0.0, 1.0, 0.0],
        "example b2": [0.0, 1.0, 0.0],
        "the query": [1.0, 0.0, 0.0],  # identical to slide_a's examples
    }
    router = EmbeddingRouter(config, embedder=FakeEmbedder(vectors), similarity_threshold=0.5, margin=0.05)
    slides, _ = await router.route("the query")
    check("a clear winner with a strong margin over the runner-up matches",
          any(s.id == "slide_a" for s in slides))


async def test_close_race_abstains():
    config = minimal_config()
    # both slides score almost identically close to the query - should
    # abstain rather than guess, since there's no real margin either way
    vectors = {
        "example a1": [1.0, 0.05, 0.0],
        "example a2": [1.0, 0.05, 0.0],
        "example b1": [1.0, 0.0, 0.0],
        "example b2": [1.0, 0.0, 0.0],
        "the query": [1.0, 0.025, 0.0],
    }
    router = EmbeddingRouter(config, embedder=FakeEmbedder(vectors), similarity_threshold=0.5, margin=0.05)
    slides, _ = await router.route("the query")
    check("a close race between two slides (no real margin) abstains instead of guessing",
          not any(s.id in ("slide_a", "slide_b") for s in slides))


async def test_below_floor_does_not_match_even_if_best():
    config = minimal_config()
    # slide_a is the "best" of the two, but nowhere near the query -
    # being the best available option isn't enough, it must also clear
    # the absolute floor
    vectors = {
        "example a1": [0.1, 0.9, 0.0],
        "example a2": [0.1, 0.9, 0.0],
        "example b1": [0.0, 1.0, 0.0],
        "example b2": [0.0, 1.0, 0.0],
        "the query": [1.0, 0.0, 0.0],  # orthogonal-ish to both
    }
    router = EmbeddingRouter(config, embedder=FakeEmbedder(vectors), similarity_threshold=0.5, margin=0.05)
    slides, _ = await router.route("the query")
    check("the best-scoring slide still doesn't match if it's below the absolute floor",
          not any(s.id in ("slide_a", "slide_b") for s in slides))


async def test_averaging_rejects_a_single_noisy_match():
    config = minimal_config()
    # slide_a: one example is a perfect match (noise), the other is
    # the OPPOSITE direction entirely. A single-best-example rule would
    # have matched on the perfect 1.0 hit alone; averaging pulls the
    # combined score down to ~0.0, clearly below the threshold.
    vectors = {
        "example a1": [1.0, 0.0, 0.0],    # perfect match to the query - the "noisy lucky hit"
        "example a2": [-1.0, 0.0, 0.0],   # opposite direction - average should cancel toward 0
        "example b1": [0.0, 1.0, 0.0],
        "example b2": [0.0, 1.0, 0.0],
        "the query": [1.0, 0.0, 0.0],
    }
    router = EmbeddingRouter(config, embedder=FakeEmbedder(vectors), similarity_threshold=0.5, margin=0.05)
    slides, _ = await router.route("the query")
    check("averaging across a slide's examples rejects a match driven by only one noisy example",
          not any(s.id == "slide_a" for s in slides))


async def main():
    await test_falls_back_without_fastembed()
    await test_hybrid_preserves_negation_on_keyword_path()
    await test_hybrid_never_loses_a_keyword_match()
    await test_clear_winner_with_margin_matches()
    await test_close_race_abstains()
    await test_below_floor_does_not_match_even_if_best()
    await test_averaging_rejects_a_single_noisy_match()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    else:
        print("ALL EMBEDDING-ROUTER (FALLBACK-MODE) TESTS PASSED")
        print("NOTE: this only verifies fallback behavior. The actual semantic")
        print("matching pass needs fastembed + a real model - test in Colab.")


if __name__ == "__main__":
    asyncio.run(main())
