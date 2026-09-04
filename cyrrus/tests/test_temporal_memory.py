"""
Temporal fact tracking tests for MemoryVault.

Tests that:
1. New facts correctly invalidate old facts (old row gets invalid_at set, new row is current)
2. Default retrieval only returns current facts (invalid_at IS NULL)
3. get_fact_history() returns the full timeline in order
4. Old facts are never deleted (row count only grows, never shrinks on update)
"""
import asyncio
import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cyrrus.memory import MemoryVault

DB = "temporal_memory_test.db"


def cleanup():
    """Clean up test database."""
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


async def test_fact_invalidation():
    """Test that a new fact correctly invalidates the old one."""
    print("\n[FACT INVALIDATION] Testing that new facts invalidate old ones.\n")
    
    memory = MemoryVault(db_path=DB)
    
    session_id = "test_session"
    keyword = "user_language"
    
    # Insert initial fact
    await memory.upsert(session_id, keyword, "Python", 1)
    
    # Wait a moment to ensure different timestamps
    await asyncio.sleep(0.1)
    
    # Update the fact
    await memory.upsert(session_id, keyword, "JavaScript", 1)
    
    # Check history - should have 2 entries
    history = await memory.get_fact_history(session_id, keyword)
    
    if len(history) == 2:
        print(f"  [PASS] History has 2 entries (old + new)")
    else:
        print(f"  [FAIL] Expected 2 history entries, got {len(history)}")
    
    # Check that the first entry is invalidated
    if history[0]["invalid_at"] is not None:
        print(f"  [PASS] Old fact has invalid_at set")
    else:
        print(f"  [FAIL] Old fact should have invalid_at set")
    
    # Check that the second entry is current
    if history[1]["invalid_at"] is None:
        print(f"  [PASS] New fact is current (invalid_at is NULL)")
    else:
        print(f"  [FAIL] New fact should be current (invalid_at should be NULL)")
    
    # Check values
    if history[0]["value"] == "Python" and history[1]["value"] == "JavaScript":
        print(f"  [PASS] Values are correct in chronological order")
    else:
        print(f"  [FAIL] Values incorrect: {history[0]['value']}, {history[1]['value']}")
    
    cleanup()


async def test_current_only_retrieval():
    """Test that default retrieval only returns current facts."""
    print("\n[CURRENT RETRIEVAL] Testing that retrieval only returns current facts.\n")
    
    memory = MemoryVault(db_path=DB)
    
    session_id = "test_session"
    
    # Insert and update a fact
    await memory.upsert(session_id, "user_language", "Python", 1)
    await asyncio.sleep(0.1)
    await memory.upsert(session_id, "user_language", "JavaScript", 1)
    
    # Insert another fact that won't be updated
    await memory.upsert(session_id, "user_name", "Alice", 1)
    
    # Retrieve facts
    slides = await memory.retrieve(session_id, "what language do I use", limit=10)
    
    # Should only get current facts (JavaScript, not Python)
    retrieved_keywords = [s.id.replace("mem_", "") for s in slides]
    
    if "user_language" in retrieved_keywords:
        print(f"  [PASS] user_language retrieved")
    else:
        print(f"  [FAIL] user_language not retrieved")
    
    # Count total rows in database
    def count_rows():
        import sqlite3
        with sqlite3.connect(DB) as conn:
            return conn.execute("SELECT COUNT(*) FROM facts WHERE session_id=?", (session_id,)).fetchone()[0]
    
    total_rows = await asyncio.to_thread(count_rows)
    
    # Should have 3 rows total (Python invalidated, JavaScript current, Alice current)
    if total_rows == 3:
        print(f"  [PASS] Database has 3 rows (history preserved)")
    else:
        print(f"  [FAIL] Expected 3 rows, got {total_rows}")
    
    # But retrieval should only return 2 current facts
    if len(slides) == 2:
        print(f"  [PASS] Retrieval returned 2 current facts only")
    else:
        print(f"  [FAIL] Expected 2 current facts, got {len(slides)}")
    
    cleanup()


async def test_fact_history_timeline():
    """Test that get_fact_history returns the full timeline in order."""
    print("\n[FACT HISTORY] Testing that get_fact_history returns ordered timeline.\n")
    
    memory = MemoryVault(db_path=DB)
    
    session_id = "test_session"
    keyword = "user_project"
    
    # Insert multiple versions
    versions = ["Project A", "Project B", "Project C", "Project D"]
    
    for i, version in enumerate(versions):
        await memory.upsert(session_id, keyword, version, 1)
        if i < len(versions) - 1:
            await asyncio.sleep(0.1)
    
    # Get history
    history = await memory.get_fact_history(session_id, keyword)
    
    if len(history) == len(versions):
        print(f"  [PASS] History has all {len(versions)} versions")
    else:
        print(f"  [FAIL] Expected {len(versions)} versions, got {len(history)}")
    
    # Check chronological order
    values = [h["value"] for h in history]
    if values == versions:
        print(f"  [PASS] History is in chronological order")
    else:
        print(f"  [FAIL] History order incorrect: {values}")
    
    # Check that only the last one is current
    current_count = sum(1 for h in history if h["invalid_at"] is None)
    if current_count == 1:
        print(f"  [PASS] Only the latest version is current")
    else:
        print(f"  [FAIL] Expected 1 current fact, got {current_count}")
    
    # Check that all others have invalid_at
    invalidated_count = sum(1 for h in history if h["invalid_at"] is not None)
    if invalidated_count == len(versions) - 1:
        print(f"  [PASS] All old versions have invalid_at set")
    else:
        print(f"  [FAIL] Expected {len(versions) - 1} invalidated, got {invalidated_count}")
    
    cleanup()


async def test_no_deletion_on_update():
    """Test that old facts are never deleted (row count only grows)."""
    print("\n[NO DELETION] Testing that old facts are never deleted.\n")
    
    memory = MemoryVault(db_path=DB)
    
    session_id = "test_session"
    
    def count_rows():
        import sqlite3
        with sqlite3.connect(DB) as conn:
            return conn.execute("SELECT COUNT(*) FROM facts WHERE session_id=?", (session_id,)).fetchone()[0]
    
    # Insert initial fact
    await memory.upsert(session_id, "fact1", "value1", 1)
    count1 = await asyncio.to_thread(count_rows)
    print(f"  After 1 insert: {count1} rows")
    
    # Update the fact multiple times
    for i in range(5):
        await memory.upsert(session_id, "fact1", f"value1_update{i}", 1)
        await asyncio.sleep(0.05)
    
    count2 = await asyncio.to_thread(count_rows)
    print(f"  After 5 updates: {count2} rows")
    
    # Row count should have grown (1 initial + 5 updates = 6 total)
    if count2 == 6:
        print(f"  [PASS] Row count grew to 6 (1 initial + 5 updates)")
    else:
        print(f"  [FAIL] Expected 6 rows, got {count2}")
    
    # Insert a different fact
    await memory.upsert(session_id, "fact2", "value2", 1)
    count3 = await asyncio.to_thread(count_rows)
    print(f"  After new fact: {count3} rows")
    
    if count3 == 7:
        print(f"  [PASS] Row count is 7 (6 from fact1 + 1 from fact2)")
    else:
        print(f"  [FAIL] Expected 7 rows, got {count3}")
    
    # Update the second fact
    await memory.upsert(session_id, "fact2", "value2_updated", 1)
    count4 = await asyncio.to_thread(count_rows)
    print(f"  After fact2 update: {count4} rows")
    
    if count4 == 8:
        print(f"  [PASS] Row count is 8 (6 from fact1 + 2 from fact2)")
    else:
        print(f"  [FAIL] Expected 8 rows, got {count4}")
    
    cleanup()


async def test_multiple_keywords_independent():
    """Test that different keywords are tracked independently."""
    print("\n[INDEPENDENT KEYWORDS] Testing that different keywords track independently.\n")
    
    memory = MemoryVault(db_path=DB)
    
    session_id = "test_session"
    
    # Insert multiple facts with different keywords
    await memory.upsert(session_id, "language", "Python", 1)
    await asyncio.sleep(0.1)
    await memory.upsert(session_id, "name", "Alice", 1)
    await asyncio.sleep(0.1)
    await memory.upsert(session_id, "framework", "Django", 1)
    
    # Update only one
    await memory.upsert(session_id, "language", "JavaScript", 1)
    
    # Check history for each keyword
    lang_history = await memory.get_fact_history(session_id, "language")
    name_history = await memory.get_fact_history(session_id, "name")
    framework_history = await memory.get_fact_history(session_id, "framework")
    
    if len(lang_history) == 2 and len(name_history) == 1 and len(framework_history) == 1:
        print(f"  [PASS] Keywords tracked independently (2, 1, 1 versions)")
    else:
        print(f"  [FAIL] Expected (2, 1, 1) versions, got ({len(lang_history)}, {len(name_history)}, {len(framework_history)})")
    
    # Check that only language has an invalidated version
    lang_invalidated = sum(1 for h in lang_history if h["invalid_at"] is not None)
    name_invalidated = sum(1 for h in name_history if h["invalid_at"] is not None)
    framework_invalidated = sum(1 for h in framework_history if h["invalid_at"] is not None)
    
    if lang_invalidated == 1 and name_invalidated == 0 and framework_invalidated == 0:
        print(f"  [PASS] Only updated keyword has invalidated version")
    else:
        print(f"  [FAIL] Invalidation counts incorrect: ({lang_invalidated}, {name_invalidated}, {framework_invalidated})")
    
    cleanup()


async def main():
    print("=" * 60)
    print("TEMPORAL FACT TRACKING TESTS")
    print("=" * 60)
    
    await test_fact_invalidation()
    await test_current_only_retrieval()
    await test_fact_history_timeline()
    await test_no_deletion_on_update()
    await test_multiple_keywords_independent()
    
    print("\n" + "=" * 60)
    print("Temporal fact tracking tests complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
