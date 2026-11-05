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

        # Integer encoding of the (keyword, doc index) total order used for the
        # deterministic tie-break, computed once here: rank_of[idx] is the
        # position of doc `idx` among docs sorted by (keyword, doc index).
        # Comparing rank_of values is therefore identical to comparing
        # (keyword, doc index) pairs, but lets rank() tie-break with a plain
        # integer key instead of building a string sort key per matching doc.
        order = sorted(
            range(self.corpus_size),
            key=lambda i: (self.facts[i][0], i),
        )
        self.rank_of = [0] * self.corpus_size
        for pos, idx in enumerate(order):
            self.rank_of[idx] = pos

        # Per-doc term frequencies are transient (built once to populate the
        # inverted index, then discarded); only the postings, df and the
        # length-normalization term are retained. doc order = facts order,
        # which is retrieve_current's ORDER BY last_accessed DESC — the same
        # order bm25_rank_facts would see, so tie-breaking matches.
        # term -> [(doc_idx, freq)] with doc_idx ascending
        self.postings: Dict[str, List[Tuple[int, int]]] = {}
        self.df: Dict[str, int] = {}
        doc_lengths: List[int] = []

        for idx, (kw, val, _tok) in enumerate(self.facts):
            kw_expanded = _expand_keyword_with_aliases(kw)
            doc = f"{kw_expanded} : {val}" if val else kw_expanded
            toks = _tokenize(doc)
            doc_lengths.append(len(toks))
            freqs: Dict[str, int] = {}
            for t in toks:
                freqs[t] = freqs.get(t, 0) + 1
            for t, f in freqs.items():
                self.df[t] = self.df.get(t, 0) + 1
                self.postings.setdefault(t, []).append((idx, f))

        if self.corpus_size == 0:
            self.avgdl = 0.0
            self.idf: Dict[str, float] = {}
            self.avg_idf = 0.0
            self.doc_norm: List[float] = []
            return

        self.avgdl = sum(doc_lengths) / self.corpus_size
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
            for dl in doc_lengths
        ]

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
        postings = self.postings
        doc_norm = self.doc_norm
        idf = self.idf
        k1p1 = self.k1 + 1.0

        # Term-oriented accumulation over postings into a flat array. Every
        # document receives a score (0.0 when no query term matches), so a
        # negative score_threshold naturally admits zero-score docs while a
        # non-negative one excludes them — identical to BM25Ranker.score_query
        # for both signs. Query-term order is preserved per document and
        # unseen terms contribute exactly 0.0, so per-doc float sums are
        # bit-identical to BM25Ranker.score_query. This is kept as a dense
        # array rather than a sparse dict: a high-frequency query can touch
        # essentially the whole corpus, where dict insertion measurably loses
        # to direct list indexing, and the array is the stable choice for both
        # few- and many-match queries.
        acc = [0.0] * self.corpus_size
        for t in query_terms:
            plist = postings.get(t)
            if plist is None:
                continue
            t_idf = idf[t]
            for idx, f in plist:
                acc[idx] += t_idf * f * k1p1 / (f + doc_norm[idx])
        filtered = [
            (idx, s) for idx, s in enumerate(acc) if s > score_threshold
        ]

        # Deterministic tie-break: (score desc, keyword asc, doc index asc),
        # identical to bm25_rank_facts. rank_of encodes (keyword, doc index) as
        # a single integer, so the per-document sort key carries no string and
        # is a 2-tuple of numbers — heap-friendly for a many-match query. The
        # keyword is unique among a session's active facts, so this total order
        # is independent of the row/recency order the index was built from.
        #
        # DELIBERATE BEHAVIOR CHANGE: ties used to break by doc index (the
        # last_accessed DESC row order), so touch() could reorder ties and a
        # cached index would diverge from a fresh ranking.
        rank_of = self.rank_of
        if len(filtered) > limit:
            top = heapq.nsmallest(
                limit, filtered, key=lambda it: (-it[1], rank_of[it[0]])
            )
        else:
            filtered.sort(key=lambda it: (-it[1], rank_of[it[0]]))
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
