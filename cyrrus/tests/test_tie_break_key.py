"""
Item 2 (phase 1d): tie-break SPEED without changing behaviour.

SessionFactIndex.rank() used to build a STRING sort key (-score, keyword, idx)
for every matching document. For a high-frequency query that touches the whole
corpus that is O(corpus) string-key builds. The rewrite pre-computes an integer
encoding of the (keyword, doc index) total order at index build time
(``rank_of``) so the per-document key is a numeric 2-tuple and the top-k is
heap-selected. The resulting ORDER must be identical to the old string key.

These tests guard the invariant that the integer key is exactly equivalent to
the string key it replaced (so rankings never change), and pin the rank_of
encoding itself. ``test_rank_of_exists_and_encodes_keyword_index_order`` fails
on the pre-change index because that attribute did not exist; the equivalence
test would fail if the integer mapping were even one position off.
"""
import heapq
import itertools
import random

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.bm25_index import SessionFactIndex


def _string_key_reference(index, query, limit, score_threshold=0.0):
    """Reproduce the OLD rank(): dense accumulate + STRING key (-score, kw, idx)."""
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


def test_rank_of_exists_and_encodes_keyword_index_order():
    """rank_of[idx] is the position of doc idx among docs sorted by
    (keyword, doc index). Fails on the pre-change index (no such attribute)."""
    # Doc order deliberately NOT alphabetical, so the encoding is exercised.
    facts = [
        ("zeta", "shared token", 2),
        ("alpha", "shared token", 2),
        ("mike", "shared token", 2),
        ("Alpha", "shared token", 2),  # case differs -> distinct ordering signal
    ]
    index = SessionFactIndex(facts)
    kws = [kw for kw, _v, _t in facts]
    order = sorted(range(len(facts)), key=lambda i: (kws[i], i))
    expected = [0] * len(facts)
    for pos, idx in enumerate(order):
        expected[idx] = pos
    assert index.rank_of == expected


def test_integer_key_selects_identically_to_string_key_under_heavy_ties():
    """Across many shuffled tie-heavy corpora, the integer-key rank() must equal
    the string-key reference AND bm25_rank_facts, bit for bit and position by
    position."""
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
                    "int-key != string-key trial=%d q=%r limit=%d\n%r\n%r"
                    % (trial, q, limit, got, ref))
                exp = bm25_rank_facts(facts, q, limit=limit, score_threshold=0.0)
                assert got == exp, (
                    "int-key != bm25_rank_facts trial=%d q=%r limit=%d\n%r\n%r"
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
