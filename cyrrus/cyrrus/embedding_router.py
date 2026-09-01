"""
Semantic router using a small local embedding model instead of exact
keyword matching - catches paraphrases ("who should I vote for")
that IntentRouter's literal trigger words ("politics", "election")
would miss entirely.

NOT imported by cyrrus/__init__.py, on purpose: this has a real
dependency (fastembed) that most users of the zero-dependency keyword
router shouldn't be forced to install. Opt in explicitly:

    from cyrrus.embedding_router import EmbeddingRouter

Design notes, stated plainly instead of left implicit:

- HYBRID, not a replacement. Keyword matching (with its existing,
  correct negation handling) runs first and always wins where it
  applies. Embedding similarity is only a second pass, catching a
  slide keyword matching missed entirely. This means every behavior
  that already worked in IntentRouter keeps working identically here.

- RELATIVE decision rule, not an absolute threshold - changed after a
  real Colab run found the absolute-threshold version had a severe
  precision problem: 12/13 diverse unrelated messages produced a false
  positive at threshold=0.5, and the auto-calibrated best-possible
  threshold only reached 75.8% accuracy separating the config's own
  same-slide vs. cross-slide example pairs. That's not a tuning
  problem - it's consistent with a well-documented property of
  sentence embedding models: cosine similarity between UNRELATED short
  texts commonly clusters around 0.4-0.7 rather than near 0, because
  many models effectively use only a subspace of their embedding
  dimension. An absolute cutoff can't reliably separate "matches" from
  "doesn't match" when unrelated pairs already score in that range.
  Fix: pick whichever slide the message is most similar to RELATIVE TO
  THE OTHERS (like a prototype/nearest-class classifier), and require
  a real margin over the runner-up before committing - not just
  "was this number bigger than some absolute constant."

- Each slide's score is the AVERAGE similarity across ALL of that
  slide's example phrases, not just the single best one. Matching
  used to fire on any ONE example clearing the bar - a single noisy
  match against one of three short phrases is a low, easily-crossed
  bar. Requiring broad agreement across a slide's whole example set is
  a real, direct fix for that specific looseness, independent of the
  threshold/margin question above.

- At most ONE slide can be added via the embedding pass per call, by
  design - a deliberate precision-over-recall trade given recall was
  already fine (6/6 in the same real run) while precision was not.
  Keyword matching is unaffected and can still catch multiple distinct
  topics in one message; only the embedding pass is now single-best.

- Negation is NOT reliably handled for the embedding-only match. A
  paraphrased negation ("please refrain from looking that up") could
  still slip through. Known, real gap - not solved here.

- similarity_threshold and margin both need real tuning against your
  own slides.json and real messages, in Colab - the defaults here are
  starting points, not verified-good values.

- Config: each slide can have an optional "examples" list in
  slides.json, separate from "triggers". Falls back to reusing
  "triggers" as examples if a slide has none.

- Testable without fastembed/network: pass a fake `embedder` (anything
  with .embed(list[str]) -> list[vector]) to test the DECISION LOGIC
  (relative ranking, margin requirement, floor requirement) with
  synthetic scores. Real semantic quality still needs a real model -
  see Slides_Embedding_Test.ipynb.
"""
import logging
from collections import defaultdict
from .data import Slide
from .negation import is_negated
from .router import IntentRouter

log = logging.getLogger("cyrrus.embedding_router")

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"  # ONNX via fastembed, no PyTorch


class EmbeddingRouter:
    def __init__(
        self,
        slides_config: dict,
        model_name: str = DEFAULT_MODEL,
        similarity_threshold: float = 0.5,
        margin: float = 0.05,
        fallback_router: object = None,
        embedder: object = None,  # inject a fake for testing; None loads the real model
    ):
        self.slides_config = slides_config
        self.model_name = model_name
        self.threshold = similarity_threshold
        self.margin = margin
        # the keyword router is both the first pass AND the fallback
        # if the embedding model can't load - fail-safe, same
        # philosophy as the rest of this library.
        self.fallback_router = fallback_router or IntentRouter(slides_config)

        self._model = embedder
        self._example_embeddings = None
        self._example_slide_ids = []
        self._np = None

        if embedder is not None:
            self._precompute_examples(embedder)
        else:
            self._load_model()

    def _load_model(self):
        try:
            from fastembed import TextEmbedding
            import numpy as np
            self._np = np
            model = TextEmbedding(model_name=self.model_name)
            self._precompute_examples(model)
            if self._model is not None:
                log.info("Embedding router ready: %d example phrases across %d slides.",
                          len(self._example_slide_ids), len(set(self._example_slide_ids)))
        except ImportError:
            log.warning("fastembed not installed - EmbeddingRouter falling back to keyword-only routing. "
                        "Install with: pip install fastembed")
        except Exception as e:
            log.warning("Embedding model failed to load (%s) - falling back to keyword-only routing.", e)

    def _precompute_examples(self, embedder):
        try:
            if self._np is None:
                import numpy as np
                self._np = np

            texts, ids = [], []
            for slide_id, data in self.slides_config.items():
                if slide_id == "core_lamp":
                    continue
                examples = data.get("examples") or data.get("triggers", [])
                for ex in examples:
                    texts.append(ex)
                    ids.append(slide_id)

            if not texts:
                log.info("No examples/triggers found in config - embedding router has nothing to match against.")
                self._model = None
                return

            embeddings = self._np.array(list(embedder.embed(texts)))
            self._model = embedder
            self._example_embeddings = embeddings
            self._example_slide_ids = ids
        except Exception as e:
            log.warning("Precomputing example embeddings failed (%s) - falling back to keyword-only routing.", e)
            self._model = None

    async def route(self, user_input: str) -> tuple:
        # Pass 1: keyword matching, exactly as IntentRouter does it -
        # correct negation handling, zero cost, always runs.
        keyword_slides, negated_ids = await self.fallback_router.route(user_input)
        matched_ids = {s.id for s in keyword_slides}
        result_slides = list(keyword_slides)

        if self._model is None:
            return result_slides, negated_ids

        # Pass 2: embedding similarity - RELATIVE ranking, not an
        # absolute cutoff. At most one slide gets added.
        try:
            query_embedding = self._np.array(list(self._model.embed([user_input]))[0])
            norms = self._np.linalg.norm(self._example_embeddings, axis=1) * self._np.linalg.norm(query_embedding)
            norms[norms == 0] = 1e-9
            similarities = self._example_embeddings.dot(query_embedding) / norms

            per_slide_sims = defaultdict(list)
            for sim, sid in zip(similarities, self._example_slide_ids):
                per_slide_sims[sid].append(sim)

            # average across ALL of a slide's examples - requires broad
            # agreement, not one noisy match against a single phrase
            candidate_scores = {
                sid: sum(sims) / len(sims)
                for sid, sims in per_slide_sims.items()
                if sid not in matched_ids and sid not in negated_ids
            }

            if candidate_scores:
                ranked = sorted(candidate_scores.items(), key=lambda kv: kv[1], reverse=True)
                best_id, best_score = ranked[0]
                runner_up_score = ranked[1][1] if len(ranked) > 1 else float("-inf")
                margin_over_runner_up = best_score - runner_up_score

                if best_score >= self.threshold and margin_over_runner_up >= self.margin:
                    data = self.slides_config[best_id]
                    result_slides.append(Slide(
                        id=best_id,
                        type=data.get("type", "data"),
                        content=data.get("content", ""),
                        tokens=data.get("tokens", 10),
                        priority=data.get("priority", 500),
                        handler=data.get("handler"),
                        active_turns=data.get("active_turns"),
                        tool_estimate_tokens=data.get("tool_estimate_tokens", 150),
                    ))
        except Exception as e:
            log.warning("Embedding similarity pass failed (%s) - returning keyword-only matches for this call.", e)

        result_slides.sort(key=lambda s: s.priority, reverse=True)
        return result_slides, negated_ids
