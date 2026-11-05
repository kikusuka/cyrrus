"""
Per-session inverted index for BM25 fact ranking.

Replicates the scoring of bm25.BM25Ranker/bm25_rank_facts EXACTLY (same
parameters, same document construction, same float operation order, same
tie-breaking) but accumulates scores only over the postings of the query
terms, using an inverted index. This keeps retrieval proportional to the
matched postings rather than the whole corpus while guaranteeing identical
rankings.

Standard library only, Python 3.9 compatible.
"""
import heapq
import math
import re
from typing import Dict, List, Sequence, Tuple

from .bm25 import _expand_keyword_with_aliases

_DROP_CAP = 100


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"\w+", text.lower())


class SessionFactIndex:
    """Inverted index over one session's active facts.

    Built from the same (keyword, value, tokens) rows that
    retrieve_current(limit=None) returns; ranking matches bm25_rank_facts
    on those rows bit-for-bit.
    """

    def __init__(
        self,
        facts: Sequence[Tuple[str, str, int]],
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ):
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.facts = list(facts)
        self.corpus_size = len(self.facts)

        # Per-doc term frequencies and lengths (doc order = facts order,
        # which is retrieve_current's ORDER BY last_accessed DESC — the same
        # order bm25_rank_facts would see, so tie-breaking matches).
        self.doc_freqs: List[Dict[str, int]] = []
        self.doc_lengths: List[int] = []
        # term -> [(doc_idx, freq)] with doc_idx ascending
        self.postings: Dict[str, List[Tuple[int, int]]] = {}
        self.df: Dict[str, int] = {}

        for idx, (kw, val, _tok) in enumerate(self.facts):
            kw_expanded = _expand_keyword_with_aliases(kw)
            doc = f"{kw_expanded} : {val}" if val else kw_expanded
            toks = _tokenize(doc)
            freqs: Dict[str, int] = {}
            for t in toks:
                freqs[t] = freqs.get(t, 0) + 1
            self.doc_freqs.append(freqs)
            self.doc_lengths.append(len(toks))
            for t, f in freqs.items():
                self.df[t] = self.df.get(t, 0) + 1
                self.postings.setdefault(t, []).append((idx, f))

        if self.corpus_size == 0:
            self.avgdl = 0.0
            self.idf: Dict[str, float] = {}
            self.avg_idf = 0.0
            self.doc_norm: List[float] = []
            return

        self.avgdl = sum(self.doc_lengths) / self.corpus_size
        self.idf = {
            term: math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in self.df.items()
        }
        idf_sum = sum(self.idf.values())
        self.avg_idf = idf_sum / len(self.idf) if self.idf else 0.0

        # Precomputed length-normalization term: k1 * (1 - b + b * dl/avgdl).
        # Identical expression to BM25Ranker._score_term's denominator part.
        self.doc_norm = [
            self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl if self.avgdl > 0 else 0.0))
            for dl in self.doc_lengths
        ]

    def _score_term(self, doc_idx: int, term: str) -> float:
        """Mirror of BM25Ranker._score_term (same float operation order)."""
        f = self.doc_freqs[doc_idx].get(term, 0)
        if f == 0:
            return 0.0
        idf = self.idf.get(term)
        if idf is None:
            idf = self.epsilon * self.avg_idf
        denominator = f + self.doc_norm[doc_idx]
        return idf * f * (self.k1 + 1.0) / denominator

    def rank(
        self,
        user_input: str,
        limit: int = 3,
        score_threshold: float = 0.0,
    ) -> Tuple[List[Tuple[float, str, str, int]], List[Dict[str, str]]]:
        """Rank facts against user_input.

        Returns (ranked, dropped) where ranked is a list of
        (score, keyword, value, tokens) — identical to
        bm25_rank_facts(facts, user_input, limit, score_threshold) — and
        dropped is a capped list of {"key": kw, "reason": "below threshold"}
        for facts not included in ranked.
        """
        if self.corpus_size == 0:
            return [], []

        query_terms = _tokenize(user_input)

        if score_threshold < 0.0:
            # Negative thresholds admit zero-score docs: score everything,
            # exactly like BM25Ranker.score_query.
            scores: Dict[int, float] = {}
            for idx in range(self.corpus_size):
                s = 0.0
                for t in query_terms:
                    s += self._score_term(idx, t)
                scores[idx] = s
            filtered = [(idx, s) for idx, s in scores.items() if s > score_threshold]
        else:
            # Term-oriented accumulation over postings into a flat array.
            # Query-term order is preserved per document and unseen terms
            # contribute exactly 0.0 in score_query, so per-doc float sums
            # are bit-identical to BM25Ranker.score_query.
            acc = [0.0] * self.corpus_size
            postings = self.postings
            doc_norm = self.doc_norm
            k1p1 = self.k1 + 1.0
            for t in query_terms:
                plist = postings.get(t)
                if plist is None:
                    continue
                idf = self.idf[t]
                for idx, f in plist:
                    acc[idx] += idf * f * k1p1 / (f + doc_norm[idx])
            filtered = [
                (idx, s) for idx, s in enumerate(acc) if s > score_threshold
            ]

        # Deterministic tie-break: (score desc, keyword asc, doc index asc).
        # The keyword is the stable fact id, so the order is independent of
        # the row/recency order the index was built from. This mirrors
        # bm25_rank_facts exactly.
        #
        # DELIBERATE BEHAVIOR CHANGE: ties used to break by doc index (the
        # last_accessed DESC row order), so touch() could reorder ties and a
        # cached index would diverge from a fresh ranking.
        facts = self.facts

        def _key(item):
            idx, score = item
            return (-score, facts[idx][0], idx)

        if len(filtered) > limit:
            top = heapq.nsmallest(limit, filtered, key=_key)
        else:
            filtered.sort(key=_key)
            top = filtered

        ranked_out = []
        for idx, score in top:
            kw, val, tok = self.facts[idx]
            ranked_out.append((score, kw, val, tok))

        included = {idx for idx, _ in top}
        dropped = []
        for idx, (kw, _v, _t) in enumerate(self.facts):
            if idx in included:
                continue
            dropped.append({"key": kw, "reason": "below threshold"})
            if len(dropped) >= _DROP_CAP:
                break
        return ranked_out, dropped
