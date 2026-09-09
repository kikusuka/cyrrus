"""
Token consistency tests for the history compression feature.

Tests that:
1. Token count stays roughly consistent even at message 20+, not decaying like before
2. Keyword extraction actually catches sentences containing memory-relevant keywords
3. Sentence deduplication works correctly
4. The "Previously mentioned:" block is properly formatted
"""
import asyncio
import os
import sys
from collections import deque

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cyrrus import Projector
from cyrrus.projector import (
    _extract_memory_sentences,
    _deduplicate_sentences,
    _build_compact_history,
)

DB = "token_consistency_test.db"


def cleanup():
    """Clean up test database."""
    import time
    for ext in ["", "-wal", "-shm"]:
        for attempt in range(3):
            try:
                os.remove(DB + ext)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.1)
                else:
                    pass


def base_config():
    return {
        "core_lamp": {"content": "You are helpful."},
        "code_lens": {
            "content": "Output only code.",
            "triggers": ["code", "script", "python"],
        },
    }


def count_tokens(text: str) -> int:
    """Simple token count (word-based)."""
    return len(text.split())


# ─── KEYWORD EXTRACTION TESTS ─────────────────────────────────────────────────

def test_keyword_extraction():
    """Test that keyword extraction catches sentences with memory-relevant markers."""
    print("\n[KEYWORD EXTRACTION] Testing memory-relevant sentence extraction.\n")
    
    # Test each keyword individually
    test_cases = [
        ("My name is John", ["name"]),
        ("I prefer coffee over tea", ["prefer"]),
        ("I like programming", ["like"]),
        ("I want to learn Python", ["want"]),
        ("I need help with this", ["need"]),
        ("I always use this approach", ["always"]),
        ("I never do that", ["never"]),
        ("Don't forget to call me", ["don't"]),
        ("You should try this", ["should"]),
        ("You must read this", ["must"]),
    ]
    
    for text, expected_keywords in test_cases:
        extracted = _extract_memory_sentences(text)
        if extracted:
            print(f"  [PASS] '{text}' -> extracted: {extracted}")
        else:
            print(f"  [FAIL] '{text}' -> no extraction (expected keyword: {expected_keywords})")
    
    # Test sentence with multiple keywords
    multi = "My name is Alice and I prefer Python. I always write clean code."
    extracted = _extract_memory_sentences(multi)
    print(f"  [INFO] Multiple keywords: '{multi}' -> {len(extracted)} sentences extracted")
    if len(extracted) >= 2:
        print(f"  [PASS] Multiple keywords extracted correctly")
    else:
        print(f"  [FAIL] Expected at least 2 sentences, got {len(extracted)}")
    
    # Test sentence without memory keywords
    no_keyword = "The weather is nice today"
    extracted = _extract_memory_sentences(no_keyword)
    if not extracted:
        print(f"  [PASS] No extraction for non-memory sentence: '{no_keyword}'")
    else:
        print(f"  [FAIL] Unexpected extraction: '{no_keyword}' -> {extracted}")


# ─── SENTENCE DEDUPLICATION TESTS ─────────────────────────────────────────────

def test_sentence_deduplication():
    """Test that near-identical sentences are deduplicated."""
    print("\n[SENTENCE DEDUPLICATION] Testing duplicate removal.\n")
    
    # Test exact duplicates
    exact_dups = [
        "My name is John",
        "My name is John",
        "My name is John",
    ]
    deduped = _deduplicate_sentences(exact_dups)
    if len(deduped) == 1:
        print(f"  [PASS] Exact duplicates removed: {len(exact_dups)} -> {len(deduped)}")
    else:
        print(f"  [FAIL] Expected 1 sentence, got {len(deduped)}")
    
    # Test near-identical sentences
    near_dups = [
        "My name is John",
        "My name is John.",
        "My name is John Smith",
    ]
    deduped = _deduplicate_sentences(near_dups)
    if len(deduped) < len(near_dups):
        print(f"  [PASS] Near-identical deduplicated: {len(near_dups)} -> {len(deduped)}")
    else:
        print(f"  [FAIL] No deduplication occurred: {len(near_dups)} -> {len(deduped)}")
    
    # Test different sentences
    different = [
        "My name is John",
        "I prefer coffee",
        "I like programming",
    ]
    deduped = _deduplicate_sentences(different)
    if len(deduped) == len(different):
        print(f"  [PASS] Different sentences preserved: {len(different)} -> {len(deduped)}")
    else:
        print(f"  [FAIL] Different sentences incorrectly deduplicated: {len(different)} -> {len(deduped)}")


# ─── COMPACT HISTORY BUILDING TESTS ───────────────────────────────────────────

def test_compact_history_building():
    """Test that compact history is built correctly."""
    print("\n[COMPACT HISTORY] Testing history compression.\n")
    
    # Test with short history (no compression needed)
    short_history = deque([
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ])
    compact = _build_compact_history(short_history, verbatim_turns=5)
    if len(compact) == len(short_history):
        print(f"  [PASS] Short history unchanged: {len(short_history)} -> {len(compact)}")
    else:
        print(f"  [FAIL] Short history modified: {len(short_history)} -> {len(compact)}")
    
    # Test with long history (compression should occur)
    long_history = deque([
        {"role": "user", "content": f"message_{i} My name is John and I prefer coffee"}
        for i in range(20)
    ])
    # Add assistant responses
    for i in range(20):
        long_history.append({"role": "assistant", "content": f"response_{i}"})
    
    compact = _build_compact_history(long_history, verbatim_turns=5)
    
    # Should have: 1 "Previously mentioned" block + 10 verbatim messages (5 turns)
    expected_verbatim = 5 * 2  # 5 turns * 2 messages per turn
    if len(compact) <= expected_verbatim + 1:  # +1 for the "Previously mentioned" block
        print(f"  [PASS] Long history compressed: {len(long_history)} -> {len(compact)}")
    else:
        print(f"  [FAIL] Long history not compressed enough: {len(long_history)} -> {len(compact)}")
    
    # Check that "Previously mentioned" block exists
    has_block = any("Previously mentioned" in m.get("content", "") for m in compact)
    if has_block:
        print(f"  [PASS] 'Previously mentioned' block present")
    else:
        print(f"  [FAIL] 'Previously mentioned' block missing")


# ─── TOKEN CONSISTENCY TESTS ─────────────────────────────────────────────────

async def test_token_consistency():
    """Test that token count stays consistent at message 20+."""
    print("\n[TOKEN CONSISTENCY] Testing token count stability over long conversations.\n")
    
    captured = []
    
    async def capture_llm(messages):
        captured.append(messages)
        return "ok"
    
    bot = Projector(
        base_config(),
        llm_call=capture_llm,
        history_window=20,
        history_verbatim_turns=5,
        memory_db_path=DB,
    )
    
    # Send 25 messages with memory-relevant content
    token_counts = []
    for i in range(25):
        message = f"My name is User{i} and I prefer option A. I always use this setting."
        await bot.process(message, session_id="test_user")
        
        # Count tokens in the last captured messages
        if captured:
            last_messages = captured[-1]
            total_tokens = sum(count_tokens(m.get("content", "")) for m in last_messages)
            token_counts.append(total_tokens)
    
    print(f"  Token counts over 25 messages: {token_counts[:5]} ... {token_counts[-5:]}")
    
    # Check that token count doesn't decay significantly
    # Compare early messages (after warmup) with late messages
    early_tokens = token_counts[10:15]  # Messages 11-15
    late_tokens = token_counts[-5:]    # Last 5 messages
    
    early_avg = sum(early_tokens) / len(early_tokens)
    late_avg = sum(late_tokens) / len(late_tokens)
    
    print(f"  Early average tokens (msgs 11-15): {early_avg:.1f}")
    print(f"  Late average tokens (msgs 21-25): {late_avg:.1f}")
    
    # Token count should stay within 20% of early average
    if abs(late_avg - early_avg) / early_avg < 0.2:
        print(f"  [PASS] Token count stable: {abs(late_avg - early_avg) / early_avg * 100:.1f}% variation")
    else:
        print(f"  [FAIL] Token count decayed: {abs(late_avg - early_avg) / early_avg * 100:.1f}% variation")
    
    # Check that late messages have "Previously mentioned" block
    if captured:
        late_messages = captured[-1]
        has_block = any("Previously mentioned" in m.get("content", "") for m in late_messages)
        if has_block:
            print(f"  [PASS] 'Previously mentioned' block in late messages")
        else:
            print(f"  [FAIL] 'Previously mentioned' block missing in late messages")
    
    cleanup()


# ─── INTEGRATION TEST ────────────────────────────────────────────────────────

async def test_integration():
    """Test the full integration with existing functionality."""
    print("\n[INTEGRATION] Testing with existing cyrrus functionality.\n")
    
    captured = []
    
    async def capture_llm(messages):
        captured.append(messages)
        return "Response"
    
    bot = Projector(
        base_config(),
        llm_call=capture_llm,
        history_window=10,
        history_verbatim_turns=4,
        memory_db_path=DB,
    )
    
    # Test normal conversation
    await bot.process("hello", session_id="user1")
    await bot.process("write some code", session_id="user1")
    await bot.process("check weather", session_id="user1")
    
    if len(captured) == 3:
        print(f"  [PASS] Normal conversation works: 3 turns processed")
    else:
        print(f"  [FAIL] Expected 3 turns, got {len(captured)}")
    
    # Test that history is being compressed
    await bot.process("My name is Alice", session_id="user1")
    await bot.process("I prefer Python", session_id="user1")
    await bot.process("I like coffee", session_id="user1")
    await bot.process("I need help", session_id="user1")
    await bot.process("I always test", session_id="user1")
    
    if captured:
        last_messages = captured[-1]
        has_block = any("Previously mentioned" in m.get("content", "") for m in last_messages)
        if has_block:
            print(f"  [PASS] Compression activated after enough history")
        else:
            print(f"  [INFO] Compression not yet activated (may need more turns)")
    
    cleanup()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("TOKEN CONSISTENCY TESTS")
    print("Testing Phase 1: History compression with keyword extraction")
    print("=" * 60)
    
    test_keyword_extraction()
    test_sentence_deduplication()
    test_compact_history_building()
    
    asyncio.run(test_token_consistency())
    asyncio.run(test_integration())
    
    print("\n" + "=" * 60)
    print("Token consistency tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
