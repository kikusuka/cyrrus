"""
The BM25 tie-break stays the string key: (-score, keyword, doc index).

Phase 1d rewrote SessionFactIndex.rank() to key on an integer encoding of the
(keyword, doc index) order precomputed at index build (``rank_of``). Phase 1e
re-measured that on the bench 50k fixture and reverted it: end-to-end medians did
not improve on either interpreter, and the extra 50k-document sort made the cold
path slower (python 3.9 first_call 6.6-10.0 s vs 3.0-3.7 s without it).

What is kept here is the part that has to survive any future rewrite: the live
rank() must select exactly what the explicit string-key reference selects, and
exactly what bm25_rank_facts selects, on tie-heavy shuffled corpora and for every
permutation of the same fact set. If the integer encoding comes back, these tests
are the parity proof, not the ``rank_of`` attribute itself.
"""
import heapq
import itertools
import random

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.bm25_index import SessionFactIndex


def _string_key_reference(index, query, limit, score_threshold=0.0):
    """rank() spelled out with the STRING key: dense accumulate + (-score, kw, idx)."""
    acc = [0.0] * index.corpus_size
    for t in query.split():
        plist = index.postings.get(t)
        if plist is None:
            continue
        t_idf = index.idf[t]
        k1p1 = index.k1 + 1.0
        for idx, f in plist:
            acc[idx] += t_idf * f * k1p1 / (f + index.doc_norm[idx])
    filtered = [(idx, s) for idx, s in enumerate(acc) if s > score_threshold]

    def _key(item):
        idx, score = item
        return (-score, index.facts[idx][0], idx)

    if len(filtered) > limit:
        top = heapq.nsmallest(limit, filtered, key=_key)
    else:
        filtered.sort(key=_key)
        top = filtered
    out = []
    for idx, score in top:
        kw, val, tok = index.facts[idx]
        out.append((score, kw, val, tok))
    return out


def test_rank_selects_identically_to_string_key_under_heavy_ties():
    """Across many shuffled tie-heavy corpora, rank() must equal the string-key
    reference AND bm25_rank_facts, bit for bit and position by position."""
    rng = random.Random(7)
    tie_vals = ["one two", "one two", "one two"]
    for trial in range(60):
        n = rng.randint(5, 40)
        kws = rng.sample(
            ["k%02d" % i for i in range(80)], n
        )
        facts = []
        for i, kw in enumerate(kws):
            # most docs share the tie value; a few carry distinct text
            val = rng.choice(tie_vals) if rng.random() < 0.7 else "solo%d" % i
            facts.append((kw, val, len(val.split())))
        rng.shuffle(facts)  # recency/row order must not matter
        index = SessionFactIndex(facts)
        for q in ("one two", "one", "solo0 solo5", "two"):
            for limit in (1, 3, 5, 100):
                got, _drop = index.rank(q, limit=limit, score_threshold=0.0)
                ref = _string_key_reference(index, q, limit)
                assert got == ref, (
                    "rank() != string key trial=%d q=%r limit=%d\n%r\n%r"
                    % (trial, q, limit, got, ref))
                exp = bm25_rank_facts(facts, q, limit=limit, score_threshold=0.0)
                assert got == exp, (
                    "rank() != bm25_rank_facts trial=%d q=%r limit=%d\n%r\n%r"
                    % (trial, q, limit, got, exp))


def test_tie_order_independent_of_row_permutation():
    """Same set of facts, every permutation: rank() output must be identical."""
    facts = [
        ("bravo", "same same", 2),
        ("alpha", "same same", 2),
        ("charlie", "same same", 2),
        ("delta", "same same", 2),
    ]
    baseline, _ = SessionFactIndex(list(facts)).rank("same", limit=4)
    for perm in itertools.permutations(facts):
        got, _ = SessionFactIndex(list(perm)).rank("same", limit=4)
        assert got == baseline, "permutation changed tie order: %r vs %r" % (got, baseline)
    assert [kw for _s, kw, _v, _t in baseline] == ["alpha", "bravo", "charlie", "delta"]
