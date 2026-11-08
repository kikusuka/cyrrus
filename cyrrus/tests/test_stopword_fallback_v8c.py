"""
v8c item 1: stopword-restoration fallback.

"do I have children" returns nothing on v8b: stopword removal strips "have",
the ONLY term present in the fact "I have two kids", leaving just "children"
(df 0). When the query, after stopword removal and pruning, matches no
document, retrieval must retry with the stopwords restored (pruning as is).
Guardrails: "who owns the project" (whose non-stopword "project" DOES match)
must NOT trigger the retry, and an all-stopwords query must keep working.
"""
import pytest

from cyrrus.bm25 import _select_query_terms
from cyrrus.memory import MemoryVault


@pytest.mark.asyncio
async def test_children_query_restores_only_stopword(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "kids.db"))
    await vault.upsert("s", "user_kids", "I have two kids", 4)
    await vault.upsert("s", "user_location", "I live in Porto", 4)
    await vault.upsert("s", "user_job", "I work at Acme", 3)
    await vault.upsert("s", "user_hobby", "woodworking", 1)
    slides = await vault.retrieve("s", "do I have children", limit=5)
    got = [s.id[4:] for s in slides]
    assert "user_kids" in got, got


@pytest.mark.asyncio
async def test_who_owns_the_project_does_not_restore_stopwords(tmp_path):
    # "project" is a non-stopword that matches, so the retry must NOT fire and
    # "who" must not be restored (project_name's "who am i" alias would
    # otherwise outrank project_owner and the relative floor drops the owner).
    vault = MemoryVault(db_path=str(tmp_path / "owns.db"))
    await vault.upsert("s", "project_name", "the Atlas project", 8)
    await vault.upsert("s", "project_deadline", "the project is due friday", 8)
    await vault.upsert("s", "project_owner", "the project owner is Sam", 8)
    slides = await vault.retrieve("s", "who owns the project", limit=5)
    got = [s.id[4:] for s in slides]
    assert "project_owner" in got, got


@pytest.mark.asyncio
async def test_all_stopword_query_still_returns_match(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "allstop.db"))
    await vault.upsert("s", "greeting", "who are you exactly", 5)
    await vault.upsert("s", "user_kids", "I have two kids", 4)
    slides = await vault.retrieve("s", "who are you", limit=5)
    got = [s.id[4:] for s in slides]
    assert "greeting" in got, got


def test_select_terms_children_restores_stopwords():
    # kids doc tokens: user kids i have two kids, in a 4-fact session. "have"
    # is the only content-term-free signal (children df 0) -> retry restores
    # it (df 1 < cutoff 2, so pruning keeps it); "i" (df 3 >= 2) prunes as is.
    df = {"kids": 1, "user": 1, "i": 3, "have": 1, "two": 1,
          "children": 0, "do": 0}
    sel, sw, high, fb = _select_query_terms(
        ["do", "i", "have", "children"], df, 4,
        max_df_fraction=0.5, remove_stopwords=True,
    )
    assert "have" in sel, sel
    assert fb is True


def test_select_terms_owns_not_restored():
    # base non-stopwords [owns, project]; project df>0 -> base has signal ->
    # no stopword restore; project comes back via the existing pruned-term path.
    df = {"who": 1, "owns": 0, "the": 3, "project": 3}
    sel, sw, high, fb = _select_query_terms(
        ["who", "owns", "the", "project"], df, 3,
        max_df_fraction=0.5, remove_stopwords=True,
    )
    assert "who" not in sel, sel
    assert sel == ["owns", "project"], sel
    assert high == ["project"], high


def test_select_terms_near_dup_keeps_rare_stopword_restore():
    # near_dup_30 guard: "where do I live" against one true location fact plus
    # ~30 look-alikes. "live" is high-df (pruned as filler) so the surviving
    # discriminator is the rare stopword "i" (df 1 of 31). The rare-stopword
    # restore that v8b shipped MUST be preserved -- dropping it collapses
    # near_dup recall to 0.667 (measured). The no-match retry fires only when
    # NO term matches, which is not the case here ("live" matches).
    df = {"live": 30, "city": 20, "home": 15, "porto": 1, "i": 1,
          "where": 0, "do": 0}
    sel, sw, high, fb = _select_query_terms(
        ["where", "do", "i", "live"], df, 31,
        max_df_fraction=0.5, remove_stopwords=True,
    )
    assert "i" in sel, sel
    assert "live" in sel, sel


@pytest.mark.asyncio
async def test_near_dup_location_survives_lookalikes(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "near_dup.db"))
    await vault.upsert("s", "user_location", "I live in Porto", 4)
    cities = ["Madrid", "Paris", "Lyon", "Rome", "Milan", "Oslo", "Bergen",
              "Cairo", "Lima", "Quito", "Bogota", "Cusco", "Brno", "Pisa"]
    heads = ["hometown", "birthplace", "previous_city", "work_city"]
    for i, c in enumerate(cities):
        kw = "la_%s_%s" % (heads[i % len(heads)], c.lower())
        await vault.upsert("s", kw,
                           "%s is a city where people live and own a home" % c, 8)
    slides = await vault.retrieve("s", "where do I live", limit=5)
    got = [s.id[4:] for s in slides]
    assert "user_location" in got, got
    assert sum(1 for g in got if g.startswith("la_")) <= 4, got
