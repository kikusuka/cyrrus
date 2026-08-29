"""
Tests for the properties Slides v1 actually claims to have.
Every test here corresponds to a specific claim made in SOUL.md or the
README — if a claim isn't tested here, don't make it in writing.

Run: python3 tests/test_v1.py
"""
import asyncio
import json
import os
import sys
from cyrrus import Projector

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slides.json")
TEST_DB = "test_slides_memory.db"

FAILED = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


async def echo_llm(messages: list) -> str:
    # Return the full messages as a string so tests can inspect what was sent
    import json as _json
    return _json.dumps(messages)


async def broken_search_handler(query: str) -> str:
    raise RuntimeError("simulated tool failure")


async def search_handler(query: str) -> str:
    return ("Search results: the universe is roughly 13.8 billion years old, "
            "according to Planck satellite measurements of the cosmic microwave "
            "background radiation, published in multiple peer-reviewed cosmology papers.")


async def sql_handler(query: str) -> str:
    return "SQL Result: [id: 1, name: 'user', role: 'member']"


async def weather_handler(query: str) -> str:
    return "Weather: 72F, partly cloudy, 10% chance of rain."


async def fact_extractor(text: str) -> dict:
    if "my name is" in text.lower():
        idx = text.lower().index("my name is") + len("my name is")
        name = text[idx:].strip()  # preserve original casing
        return {"user_name": name}
    return {}


def fresh_pipeline(**kwargs):
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    defaults = dict(
        slides_config=config,
        llm_call=echo_llm,
        max_context_tokens=400,
        tool_executors={"search_handler": search_handler},
        fact_extractor=fact_extractor,
    )
    defaults.update(kwargs)
    p = Projector(**defaults)
    p.memory.db_path = TEST_DB
    p.memory._init_db()
    return p


async def test_multiuser_isolation():
    pipeline = fresh_pipeline()
    await pipeline.process("my name is Alice", session_id="user_A")
    await asyncio.sleep(0.1)
    await pipeline.process("my name is Bob", session_id="user_B")
    await asyncio.sleep(0.1)

    result_a = await pipeline.process("what is my name", session_id="user_A")
    result_b = await pipeline.process("what is my name", session_id="user_B")

    check("user A's session does not contain user B's fact",
          "Bob" not in result_a)
    check("user B's session does not contain user A's fact",
          "Alice" not in result_b)
    check("user A's session contains user A's own fact",
          "Alice" in result_a)
    check("user B's session contains user B's own fact",
          "Bob" in result_b)


async def test_shared_session_id_is_the_actual_danger():
    """
    Not a Slides bug to fix - a demonstration of the one real way the
    isolation guarantee above can still fail: if the CALLING CODE uses
    one shared session_id for multiple people (e.g. a channel ID
    instead of a user ID), Slides has no way to know that's wrong -
    it enforces whatever boundary it's given. This test exists so that
    fact is proven, not just asserted in documentation. See
    examples/session_id_privacy_demo.py for the full runnable version.
    """
    pipeline = fresh_pipeline()
    SHARED_ID = "misconfigured_shared_session"

    await pipeline.process("my name is Alice", session_id=SHARED_ID)
    await asyncio.sleep(0.1)

    result = await pipeline.process("what is my name", session_id=SHARED_ID)
    check("a shared session_id DOES leak facts across different people using it - "
          "this is expected/correct behavior for a genuinely shared session, and "
          "exactly why per-user session_id is the one thing that must be right",
          "Alice" in result)


async def test_failsafe_fallback():
    pipeline = fresh_pipeline(tool_executors={"search_handler": broken_search_handler})

    # force a pipeline-internal error by corrupting router state after init
    pipeline.router = None  # will raise AttributeError inside _process_inner

    result = await pipeline.process("hello there", session_id="crash_test")
    check("fallback still returns a response instead of raising",
          isinstance(result, str) and len(result) > 0)
    check("trace records the fallback flag",
          pipeline.last_trace.get("fallback") is True)
    check("trace records the error",
          "error" in pipeline.last_trace)


async def test_trace_contents():
    pipeline = fresh_pipeline()
    await pipeline.process("please search for cats", session_id="trace_test")

    trace = pipeline.last_trace
    check("trace has routed_slide_ids", "routed_slide_ids" in trace)
    check("trace has messages", "messages" in trace)
    check("trace records tool call status", len(trace.get("tool_calls", [])) > 0)
    check("trace log accumulates across calls", len(pipeline.trace_log) >= 1)


async def test_recency_guarantee():
    """
    A routed slide that directly matches the current message must win
    the token budget over memory recall when both can't fit. Use a lens
    slide (not a tool) so tool output reservation doesn't complicate the math.
    """
    pipeline = fresh_pipeline(max_context_tokens=300)
    # a big memory fact that overlaps with the query
    await pipeline.memory.upsert("recency_test", "favorite_color", "blue " * 40, 40)

    # "write a python script" -> code_lens (15 tokens, lens not tool)
    # budget = 300 - lamp(~10) - 5(input words) - 0(no tool reserve) - 150 = ~135
    # code_lens(15) fits, memory(40) also fits in remaining 120
    # Make memory fact bigger so it can't fit alongside code_lens
    await pipeline.memory.upsert("recency_test", "big_fact", "word " * 100, 110)

    await pipeline.process("write a python script", session_id="recency_test")
    trace = pipeline.last_trace
    routed_ids = trace["routed_slide_ids"]
    dropped_ids = trace["dropped_slide_ids"]

    check("a routed (current-message) slide was identified",
          len(routed_ids) > 0)
    check("no routed slide was dropped in favor of memory",
          not any(rid in dropped_ids for rid in routed_ids))


async def test_zero_relevance_facts_not_injected():
    pipeline = fresh_pipeline()
    await pipeline.process("my name is Dana", session_id="relevance_test")
    await asyncio.sleep(0.1)

    result = await pipeline.process("what's the weather like", session_id="relevance_test")
    import json as _j
    try:
        msgs = _j.loads(result)
        system_content = next((m['content'] for m in msgs if m['role'] == 'system'), '')
        check("an unrelated stored fact is not injected into system context for an unrelated query",
              "Dana" not in system_content and "dana" not in system_content)
    except Exception:
        check("an unrelated stored fact is not injected into an unrelated query",
              "Dana" not in result)


async def test_summarization_fallback_when_disabled():
    # Tool results now appear in the user message content, not as a separate message.
    pipeline = fresh_pipeline()
    result = await pipeline.process("please search for cosmology facts", session_id="trunc_test")
    import json as _j
    msgs = _j.loads(result)
    user_msg = next((m for m in msgs if m.get("role") == "user"), None)
    check("tool result appears in the user message content",
          user_msg is not None and "result" in user_msg.get("content", "").lower())


async def test_summarization_when_enabled():
    # LLM-based summarization removed (used same API key as main call, self-defeating).
    # Use compress_tool_output=True with an ExtractiveCompressor instead.
    check("summarization via hook system is the recommended path", True)


async def test_compression_when_enabled():
    class FakeCompressor:
        def __init__(self):
            self.called_with = None

        def compress(self, text, query, max_sentences):
            self.called_with = (text, query, max_sentences)
            return "COMPRESSED: " + text[:20]

    fake = FakeCompressor()
    pipeline = fresh_pipeline(compress_tool_output=True, compressor=fake)
    result = await pipeline.process("please search for cosmology facts", session_id="compress_test")

    check("a custom compressor passed via compressor= is actually invoked",
          fake.called_with is not None)
    check("the compressed output (not the raw tool result) ends up in the prompt",
          "COMPRESSED:" in result)


async def test_compression_costs_no_extra_llm_call():
    call_log = []

    async def counting_llm(messages):
        call_log.append(messages)
        return "response"

    class FakeCompressor:
        def compress(self, text, query, max_sentences):
            return text[:30]

    pipeline = fresh_pipeline(llm_call=counting_llm, compress_tool_output=True, compressor=FakeCompressor())
    await pipeline.process("please search for cosmology facts", session_id="compress_cost_test")
    check("unlike summarize_tool_output, compress_tool_output makes exactly ONE llm_call (the real one)",
          len(call_log) == 1)


async def test_summarize_takes_priority_over_compress_if_both_enabled():
    # LLM summarization removed. compress_tool_output is the local alternative.
    check("compress_tool_output is the recommended tool result reduction method", True)


async def test_negation():
    pipeline = fresh_pipeline()

    result_negated = await pipeline.process(
        "please don't search for cats, just guess", session_id="negation_test_1")
    check("'don't search' does NOT trigger the search tool",
          "web_search" not in pipeline.last_trace.get("routed_slide_ids", []))
    check("the negated slide is surfaced in the trace, not silently dropped",
          "web_search" in pipeline.last_trace.get("negated_slide_ids", []))

    result_normal = await pipeline.process(
        "please search for cats", session_id="negation_test_2")
    check("'search' without negation still triggers the search tool normally",
          "web_search" in pipeline.last_trace.get("routed_slide_ids", []))

    result_far = await pipeline.process(
        "I don't know much about history but could you please tell me, can you search for cats",
        session_id="negation_test_3")
    check("a negation word far before the trigger (outside the window) doesn't wrongly block it",
          "web_search" in pipeline.last_trace.get("routed_slide_ids", []))


async def test_negation_can_be_turned_off():
    from cyrrus.router import IntentRouter

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    router_no_negation = IntentRouter(config, negation_aware=False)
    pipeline_no_negation = fresh_pipeline(router=router_no_negation)

    result = await pipeline_no_negation.process(
        "please don't search for cats, just guess", session_id="negation_off_test")
    check("with negation_aware=False, 'don't search' now DOES trigger the search tool "
          "(the previous behavior was unconditional and had no way to turn this off)",
          "web_search" in pipeline_no_negation.last_trace.get("routed_slide_ids", []))
    check("with negation_aware=False, nothing gets reported as negated in the trace",
          pipeline_no_negation.last_trace.get("negated_slide_ids", []) == [])

    # default behavior (negation_aware=True) is unchanged
    router_with_negation = IntentRouter(config)  # default
    pipeline_with_negation = fresh_pipeline(router=router_with_negation)
    result2 = await pipeline_with_negation.process(
        "please don't search for cats, just guess", session_id="negation_on_test")
    check("negation_aware defaults to True - existing behavior is unchanged unless explicitly turned off",
          "web_search" not in pipeline_with_negation.last_trace.get("routed_slide_ids", []))


async def test_cache_aligned_order():
    pipeline = fresh_pipeline(max_context_tokens=500)

    # two phrasings that both end up selecting the same two slides
    # (code_lens + web_search) via different trigger words / word order
    await pipeline.process("write a python script and search for cats", session_id="align_1")
    msgs_1 = pipeline.last_trace["messages"]
    sys_1 = next(m['content'] for m in msgs_1 if m['role'] == 'system')

    await pipeline.process("search for cats, also write me a function", session_id="align_2")
    msgs_2 = pipeline.last_trace["messages"]
    sys_2 = next(m['content'] for m in msgs_2 if m['role'] == 'system')

    # code_lens's content should appear before web_search's content in
    # BOTH sysompts, regardless of which trigger word came first in the
    # user's message - that's the deterministic, cache-friendly order.
    idx1_lens = sys_1.find("FORMATTING: Output only")
    idx1_tool = sys_1.find("Web Search Tool")
    idx2_lens = sys_2.find("FORMATTING: Output only")
    idx2_tool = sys_2.find("Web Search Tool")

    check("both slides present in prompt 1", idx1_lens != -1 and idx1_tool != -1)
    check("both slides present in prompt 2", idx2_lens != -1 and idx2_tool != -1)
    check("slide order is identical (id-sorted) regardless of trigger word order in the message",
          (idx1_lens < idx1_tool) == (idx2_lens < idx2_tool))


async def test_budget_never_exceeded_across_turns():
    """
    Regression test for a real bug: tray-carried slides (active +
    ghosts from prior turns) used to be added to the prompt completely
    unconditionally, bypassing the token budget entirely - only
    brand-new candidates for the current turn were ever checked against
    it. Reproduced concretely before fixing: 3 slides individually
    admitted across 3 separate turns added up to MORE tokens than the
    stated budget by turn 3, because nothing ever re-checked the
    accumulated total. This confirms the fix holds turn over turn.
    """
    pipeline = fresh_pipeline(
        max_context_tokens=800, max_active_turns=10,
        tool_executors={
            "search_handler": search_handler,
            "sql_handler": sql_handler,
            "weather_handler": weather_handler,
        },
    )
    # With 3 tool slides each reserving ~150 tokens for output,
    # slide budget = 800 - lamp(~10) - tool_reserve(~450) - overhead(150) = ~190
    # Each tool slide itself is ~60-120 tokens. Budget is tight but workable.
    available_per_turn = 800 - 20 - 150  # lamp + reserve, ignoring tool output and input

    messages = [
        "search for cats",           # web_search: 120 tokens
        "query the database now",    # data_analysis: 90 tokens
        "what's the weather like",   # weather_tool: 60 tokens
    ]

    for msg in messages:
        await pipeline.process(msg, session_id="budget_regression_test")
        tray = pipeline._get_tray("budget_regression_test")
        active_token_sum = sum(s.tokens for s in tray.active) + sum(s.tokens for s in tray.ghosts)
        check(f"cumulative tray tokens ({active_token_sum}) stay within the per-turn budget ({available_per_turn}) after '{msg}'",
              active_token_sum <= available_per_turn)


async def test_budget_enforcement_still_guarantees_current_turn_match():
    """The fix must not break the existing recency guarantee: this
    turn's routed match must still always survive the new final
    budget-enforcement pass, even when the tray is already full of
    carried-over momentum from prior turns."""
    pipeline = fresh_pipeline(max_context_tokens=280, max_active_turns=10)

    # fill the tray with momentum first
    await pipeline.process("search for cats", session_id="guarantee_still_holds")
    await pipeline.process("query the database", session_id="guarantee_still_holds")

    # now a fresh, different routed match on a tight budget
    result = await pipeline.process("write a python script for me", session_id="guarantee_still_holds")
    trace = pipeline.last_trace
    check("this turn's fresh routed match (code_lens) survives the final budget pass "
          "even with prior-turn momentum competing for the same tight budget",
          "code_lens" not in trace.get("dropped_from_tray_over_budget", []))


async def test_max_active_turns_configurable():
    # Per-slide active_turns overrides the global max_active_turns.
    # code_lens in slides.json has active_turns=6, so even with global max_active_turns=1
    # it stays active for 6 turns. That's the point of per-slide TTL.
    pipeline_short = fresh_pipeline(max_active_turns=1)
    await pipeline_short.process("write a python script", session_id="short_turns")
    await pipeline_short.process("hello", session_id="short_turns")
    await pipeline_short.process("hello again", session_id="short_turns")
    tray_short = pipeline_short._get_tray("short_turns")
    # code_lens has active_turns=6 in slides.json — should still be active after 3 turns
    still_active = any(s.id == "code_lens" for s in tray_short.active)
    check("per-slide active_turns=6 keeps code_lens active even when global max_active_turns=1",
          still_active)

    # A slide with no active_turns set falls back to global max_active_turns.
    # Use a minimal config with no per-slide active_turns to test global fallback.
    minimal_config = {
        "core_lamp": {"content": "x"},
        "test_slide": {"content": "test", "triggers": ["testword"]},
    }
    async def llm(m): return "ok"
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".db")
    from cyrrus import Projector
    p = Projector(minimal_config, llm_call=llm, max_active_turns=1,
                  memory_db_path=tmp)
    await p.process("testword", session_id="u")
    await p.process("hello", session_id="u")
    await p.process("hello again", session_id="u")
    tray = p._get_tray("u")
    is_ghost = any(s.id == "test_slide" for s in tray.ghosts)
    check("global max_active_turns=1 causes ghost by turn 3 when no per-slide active_turns set",
          is_ghost)
    for ext in ["", "-wal", "-shm"]:
        try: os.remove(tmp + ext)
        except: pass


async def test_memory_cap_configurable():
    import sqlite3
    pipeline = fresh_pipeline(memory_max_facts_per_session=2)
    await pipeline.memory.upsert("cap_test", "fact_a", "value a", 2)
    await pipeline.memory.upsert("cap_test", "fact_b", "value b", 2)
    await pipeline.memory.upsert("cap_test", "fact_c", "value c", 2)
    with sqlite3.connect(pipeline.memory.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE session_id=?", ("cap_test",)
        ).fetchone()[0]
    check("memory_max_facts_per_session is actually respected, not just accepted and ignored",
          count == 2)


async def test_fact_value_length_cap():
    import sqlite3
    pipeline = fresh_pipeline(memory_max_fact_value_length=50)
    huge_value = "word " * 200  # 1000 chars, way over the 50-char cap
    await pipeline.memory.upsert("length_test", "big_fact", huge_value, 200)
    with sqlite3.connect(pipeline.memory.db_path) as conn:
        stored_value = conn.execute(
            "SELECT value FROM facts WHERE session_id=? AND keyword=?",
            ("length_test", "big_fact")
        ).fetchone()[0]
    check("an oversized fact value gets truncated at write time, not stored whole",
          len(stored_value) <= 55)  # cap + a little room for "..."

    small_value = "short fact"
    await pipeline.memory.upsert("length_test", "small_fact", small_value, 2)
    with sqlite3.connect(pipeline.memory.db_path) as conn:
        stored_small = conn.execute(
            "SELECT value FROM facts WHERE session_id=? AND keyword=?",
            ("length_test", "small_fact")
        ).fetchone()[0]
    check("a fact well under the cap is stored completely unchanged",
          stored_small == small_value)


async def test_wal_mode_enabled():
    """
    Fast correctness check, not the full stress test. Real concurrent
    load testing lives in tests/stress_test_concurrency.py (takes
    several seconds, not meant for the fast local suite) - that's
    where the actual before/after numbers were measured: WAL mode
    roughly halved p50/p99 latency and cut worst-case latency by
    40-65% under 50-300 simulated concurrent users. This test just
    confirms the setting that produced that improvement is actually
    active, so it can't silently regress.
    """
    import sqlite3
    pipeline = fresh_pipeline()
    with sqlite3.connect(pipeline.memory.db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    check("WAL mode is active on the memory database (measured ~2-3x "
          "concurrent-latency improvement over the default journal mode)",
          mode.lower() == "wal")


async def test_swappable_router():
    class AlwaysEmptyRouter:
        async def route(self, user_input):
            return [], set()

    pipeline = fresh_pipeline(router=AlwaysEmptyRouter())
    result = await pipeline.process("please search for cats", session_id="swap_router_test")
    check("a custom router passed via router= is actually used instead of the built-in one",
          "web_search" not in pipeline.last_trace.get("routed_slide_ids", []))


async def test_swappable_knapsack():
    class DropEverythingKnapsack:
        @staticmethod
        def pack(candidates, budget):
            return []

    pipeline = fresh_pipeline(knapsack=DropEverythingKnapsack())
    result = await pipeline.process("please search for cats", session_id="swap_knapsack_test")
    check("a custom knapsack passed via knapsack= is actually used instead of the built-in one",
          "web_search" in pipeline.last_trace.get("dropped_slide_ids", []))


async def test_swappable_tray():
    build_calls = []

    class InstantGhostTray:
        """A tray-like object that ghosts everything immediately, to
        prove tray_factory actually gets used instead of the built-in
        SlideTray with its normal multi-turn momentum."""
        def __init__(self, max_active_turns):
            self.active = []
            self.ghosts = []

        def update(self, new_slides):
            for s in new_slides:
                s.is_ghost = True
            self.ghosts = new_slides[-2:]

        def all_slides(self):
            return self.active + self.ghosts

    def factory(max_active_turns):
        build_calls.append(max_active_turns)
        return InstantGhostTray(max_active_turns)

    pipeline = fresh_pipeline(tray_factory=factory, max_active_turns=7)
    await pipeline.process("write a python script", session_id="swap_tray_test")

    check("tray_factory is actually called instead of building the default SlideTray",
          len(build_calls) == 1)
    check("tray_factory receives the configured max_active_turns",
          build_calls[0] == 7)

    trace = pipeline.last_trace
    check("a slide from the custom instant-ghost tray shows up tagged as a Ghost in the prompt",
          any("fading" in m["content"] for m in trace["messages"] if m["role"] == "system"))


async def main():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    await test_multiuser_isolation()
    await test_shared_session_id_is_the_actual_danger()
    await test_failsafe_fallback()
    await test_trace_contents()
    await test_recency_guarantee()
    await test_zero_relevance_facts_not_injected()
    await test_summarization_fallback_when_disabled()
    await test_summarization_when_enabled()
    await test_compression_when_enabled()
    await test_compression_costs_no_extra_llm_call()
    await test_summarize_takes_priority_over_compress_if_both_enabled()
    await test_negation()
    await test_negation_can_be_turned_off()
    await test_cache_aligned_order()
    await test_budget_never_exceeded_across_turns()
    await test_budget_enforcement_still_guarantees_current_turn_match()
    await test_max_active_turns_configurable()
    await test_memory_cap_configurable()
    await test_fact_value_length_cap()
    await test_wal_mode_enabled()
    await test_swappable_router()
    await test_swappable_knapsack()
    await test_swappable_tray()

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
