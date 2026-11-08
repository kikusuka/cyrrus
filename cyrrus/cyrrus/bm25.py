"""
Pure Python BM25 (Okapi BM25) implementation for fact retrieval.

BM25 is a bag-of-words retrieval function that scores a set of documents
based on the query terms appearing in each document, regardless of their
proximity. This is the same scoring approach used by Lucene/Elasticsearch
and SQLite FTS5, suitable for ranking 100s-1000s of stored facts with
zero external dependencies.

Standard Okapi BM25 formula:
    score(D, Q) = sum_i IDF(q_i) *
        f(q_i, D) * (k1 + 1) /
        (f(q_i, D) + k1 * (1 - b + b * |D| / avgdl))

Default parameters follow the literature: k1=1.5, b=0.75.
"""
import math
import re
from typing import List, Tuple, Sequence, Dict, Set


# Query-side stopwords; rare ones are restored only if df-pruning empties the query.
STOPWORDS = frozenset("""
a an and are as at be been but by do does for from had has have i if in into
is it its me my of on or our she that the their them then there these they
this to was we were what when where which who why will with you your
""".split())

# Below this df fraction a stopword still discriminates, so the fallback keeps it.
_RARE_STOPWORD_FRACTION = 0.1


def _select_query_terms(
    query_terms: Sequence[str],
    df: Dict[str, int],
    corpus_size: int,
    max_df_fraction: float = 0.5,
    remove_stopwords: bool = True,
):
    """Choose the query terms that carry ranking signal.

    Stopwords are removed first, then terms present in at least
    ``max_df_fraction`` of the corpus are pruned as filler.  If pruning would
    leave no matching term, the pruned terms are restored but stopword removal
    is kept -- except rare stopwords (df/corpus < _RARE_STOPWORD_FRACTION),
    which still discriminate.  A query that is all stopwords is returned
    unchanged.

    Returns (selected, stopwords, high_df, fallback).
    """
    raw = list(query_terms)
    stopwords = [t for t in raw if remove_stopwords and t in STOPWORDS]
    base = [t for t in raw if t not in STOPWORDS] if remove_stopwords else raw
    if not base:
        return raw, stopwords, [], True

    high_df = []
    if (
        corpus_size > 0
        and max_df_fraction is not None
        and 0 <= max_df_fraction < 1.0
    ):
        cutoff = max_df_fraction * corpus_size
        kept = []
        for term in base:
            freq = df.get(term, 0)
            if freq > 0 and freq >= cutoff:
                high_df.append(term)
            else:
                kept.append(term)
        if kept and any(df.get(term, 0) > 0 for term in kept):
            return kept, stopwords, high_df, False
        # Undo pruning but keep stopword removal; restore only rare stopwords.
        rare = [t for t in stopwords
                if df.get(t, 0) > 0
                and df[t] / corpus_size < _RARE_STOPWORD_FRACTION]
        fallback_terms = [t for t in raw if t in base or t in rare]
        return fallback_terms, stopwords, high_df, True

    return base, stopwords, high_df, False


class BM25Ranker:
    """
    BM25 ranker for scoring documents against a query.

    Documents can be any sequence of strings. Each document is tokenized
    internally so callers don't need to pre-tokenize.

    Usage:
        ranker = BM25Ranker(documents)
        scores = ranker.score_query("user query string")
        top_indices, top_scores = ranker.top_k("user query", k=3)
    """

    def __init__(
        self,
        documents: Sequence[str],
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ):
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.corpus_size = len(documents)

        # Tokenize each document: list of token lists
        self.doc_tokens: List[List[str]] = [self._tokenize(d) for d in documents]
        self.doc_lengths: List[int] = [len(toks) for toks in self.doc_tokens]

        # Guard against empty corpus
        if self.corpus_size == 0:
            self.avgdl = 0.0
            self.df: dict = {}
            self.idf: dict = {}
            return

        self.avgdl = sum(self.doc_lengths) / self.corpus_size

        # Compute document frequency (df): term -> number of docs containing it
        self.df: dict = {}
        for toks in self.doc_tokens:
            unique = set(toks)
            for term in unique:
                self.df[term] = self.df.get(term, 0) + 1

        # Compute IDF for each term. Use the Robertson-Walker form:
        # IDF(t) = log( (N - df(t) + 0.5) / (df(t) + 0.5) + 1 )
        # This is always positive and avoids negative scores.
        self.idf: dict = {}
        for term, freq in self.df.items():
            self.idf[term] = math.log(
                (self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0
            )

        # Compute average idf for terms with negative idf (rare case, handled
        # by epsilon smoothing for terms not seen in corpus).
        idf_sum = sum(self.idf.values())
        self.avg_idf = idf_sum / len(self.idf) if self.idf else 0.0

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Lowercase and tokenize text to words (letters/digits only)."""
        if not text:
            return []
        return re.findall(r"\w+", text.lower())

    def _term_freq(self, doc_idx: int, term: str) -> int:
        """Count occurrences of term in document doc_idx."""
        toks = self.doc_tokens[doc_idx]
        return toks.count(term)

    def _score_term(self, doc_idx: int, term: str) -> float:
        """Score contribution of a single query term to a document."""
        f = self._term_freq(doc_idx, term)
        if f == 0:
            return 0.0

        idf = self.idf.get(term)
        if idf is None:
            # Term not in corpus: epsilon-smoothing using average idf.
            idf = self.epsilon * self.avg_idf

        dl = self.doc_lengths[doc_idx]
        denominator = f + self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl if self.avgdl > 0 else 0.0))
        return idf * f * (self.k1 + 1.0) / denominator

    def score_query(
        self,
        query: str,
        max_df_fraction: float = 1.0,
        remove_stopwords: bool = False,
        term_meta: dict = None,
    ) -> List[float]:
        """
        Score every document in the corpus against the query.

        Returns a list of scores in the same order as the input documents.
        ``max_df_fraction`` / ``remove_stopwords`` default to the historical
        behavior; ``bm25_rank_facts`` opts into the selective defaults.
        """
        if self.corpus_size == 0:
            return []

        raw_terms = self._tokenize(query)
        query_terms, stopwords, high_df, fallback = _select_query_terms(
            raw_terms,
            self.df,
            self.corpus_size,
            max_df_fraction=max_df_fraction,
            remove_stopwords=remove_stopwords,
        )
        if term_meta is not None:
            term_meta.update({
                "query_terms": raw_terms,
                "selected_terms": query_terms,
                "stopword_terms": stopwords,
                "high_df_terms": high_df,
                "matched_terms": [t for t in query_terms if self.df.get(t, 0) > 0],
                "fallback_all_terms": fallback,
                "max_df_fraction": max_df_fraction,
            })
        scores = [0.0] * self.corpus_size

        for q_term in query_terms:
            for i in range(self.corpus_size):
                scores[i] += self._score_term(i, q_term)

        return scores

    def top_k(
        self,
        query: str,
        k: int = 3,
        score_threshold: float = 0.0,
    ) -> Tuple[List[int], List[float]]:
        """
        Return the top-k document indices and their scores.

        Args:
            query: The query string.
            k: Maximum number of results to return.
            score_threshold: Minimum score to include a result (default 0.0,
                i.e. anything that matched at least one term). Use a higher
                value to suppress weak matches.

        Returns:
            (indices, scores) both sorted by score descending.
        """
        scores = self.score_query(query)
        if not scores:
            return [], []

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        filtered = [(i, s) for i, s in ranked if s > score_threshold]
        top = filtered[:k]
        if not top:
            return [], []
        indices, scores_out = zip(*top)
        return list(indices), list(scores_out)


KEY_ALIASES: dict = {
    "location": "live living home city from based moved residence address country place",
    "name": "name called call identity known who am i",
    "employer": "work works job company employed organization workplace employer",
    "workplace": "work works job company employed organization employer office",
    "job": "work works job position role career employment workplace",
    "company": "work works job employer business firm workplace organization",
    "preference": "like love prefer favorite favour want desire choice taste",
    "language": "speak language code coding programming write speak tongue",
    "project": "project work building making creating app library repo repository application",
    "pet": "pet dog cat animal companion puppy kitten",
    "email": "email mail contact address e-mail inbox",
    "phone": "phone telephone mobile number cell contact call",
    "age": "age years old birthday born birth how old",
    "hobby": "hobby pastime activity enjoy like interest past time recreation",
}


def _expand_keyword_with_aliases(keyword: str) -> str:
    """
    Expand a snake_case keyword like "user_location" into a space-separated
    string containing the keyword tokens plus all known aliases for its
    semantic head (e.g. "location" -> "live living home city ...").

    This makes BM25 match question-style queries like "where do I live?"
    against facts whose keyword is user_location.
    """
    tokens = keyword.lower().replace("_", " ").split()
    expanded = list(tokens)
    for t in tokens:
        if t in KEY_ALIASES:
            expanded.extend(KEY_ALIASES[t].split())
    return " ".join(expanded)


def bm25_rank_facts(
    facts: Sequence[Tuple[str, str, int]],
    user_input: str,
    limit: int = 3,
    score_threshold: float = 0.0,
    max_df_fraction: float = 0.5,
    remove_stopwords: bool = True,
    return_terms: bool = False,
):
    """
    Convenience helper: rank a list of memory facts using BM25.

    Each fact is a tuple (keyword, value, tokens). Each document is built
    as "{expanded_keyword_with_aliases} : value" so that question-style
    queries (e.g. "where do I live?") match facts whose keyword is
    something like user_location (via the "location" alias set).

    Terms present in at least ``max_df_fraction`` of the facts are ignored
    (unless that removes every term) and common stopwords are dropped; pass
    ``max_df_fraction=1.0, remove_stopwords=False`` for the old ranking.

    Returns a list of (score, keyword, value, tokens) sorted by score
    descending, truncated to `limit` entries and filtered by
    `score_threshold`.  With ``return_terms=True`` returns
    ``(results, term_meta)``.
    """
    if not facts:
        return ([], {}) if return_terms else []

    # Build documents: "expanded_keyword : value" so aliases boost recall
    documents = []
    for kw, val, _tok in facts:
        kw_expanded = _expand_keyword_with_aliases(kw)
        if val:
            documents.append(f"{kw_expanded} : {val}")
        else:
            documents.append(kw_expanded)

    ranker = BM25Ranker(documents)
    term_meta = {}
    scores = ranker.score_query(
        user_input,
        max_df_fraction=max_df_fraction,
        remove_stopwords=remove_stopwords,
        term_meta=term_meta,
    )
    # Deterministic tie-break: (score desc, keyword asc, index asc). The
    # keyword is the stable fact id and is unique among a session's active
    # facts, so this total order is independent of the row/recency order the
    # facts were fetched in.
    #
    # DELIBERATE BEHAVIOR CHANGE: ties previously broke by document index,
    # i.e. the last_accessed DESC row order, which made ranking depend on
    # touch(). Both bm25_rank_facts and SessionFactIndex now tie-break by
    # fact id so a cached index and a fresh ranking always agree.
    order = sorted(
        range(len(facts)),
        key=lambda i: (-scores[i], facts[i][0], i),
    )
    results = []
    for i in order:
        score = scores[i]
        if score <= score_threshold:
            continue
        kw, val, tok = facts[i]
        results.append((score, kw, val, tok))
        if len(results) >= limit:
            break
    return (results, term_meta) if return_terms else results
