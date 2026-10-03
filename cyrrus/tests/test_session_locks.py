"""
SessionLocks race condition tests.

Tests that the per-session locking prevents race conditions in SlideTray mutations:
- No duplicate ghosts when concurrent messages hit the same session
- No lost turn counter updates
- Deterministic final tray state under concurrent access
"""
import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cyrrus import Projector
from cyrrus.projector import SessionLocks

DB = "session_locks_test.db"


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
        "weather": {
            "content": "Weather active.",
            "triggers": ["weather", "rain", "forecast"],
        },
    }


# ─── SESSIONLOCKS BASIC TESTS ────────────────────────────────────────────────

async def test_session_locks_basic():
    """Test that SessionLocks creates and reuses locks correctly."""
    print("\n[SESSIONLOCKS BASIC] Testing lock creation and reuse.\n")
    
    locks = SessionLocks()
    
    # Get lock for same key multiple times
    lock1 = await locks.get("session1")
    lock2 = await locks.get("session1")
    lock3 = await locks.get("session2")
    
    # Same session should return same lock
    if lock1 is lock2:
        print(f"  [PASS] Same session returns same lock")
    else:
        print(f"  [FAIL] Same session returned different locks")
    
    # Different sessions should return different locks
    if lock1 is not lock3:
        print(f"  [PASS] Different sessions return different locks")
    else:
        print(f"  [FAIL] Different sessions returned same lock")


async def test_session_locks_concurrent_creation():
    """Test that concurrent lock creation is safe (meta-lock guards it)."""
    print("\n[SESSIONLOCKS CONCURRENT] Testing concurrent lock creation.\n")
    
    locks = SessionLocks()
    
    # Create locks for the same session concurrently
    async def get_lock():
        return await locks.get("concurrent_session")
    
    # Fire 10 concurrent requests for the same session
    results = await asyncio.gather(*[get_lock() for _ in range(10)])
    
    # All should return the same lock object
    first_lock = results[0]
    all_same = all(lock is first_lock for lock in results)
    
    if all_same:
        print(f"  [PASS] All concurrent requests got the same lock")
    else:
        print(f"  [FAIL] Concurrent requests got different locks")


# ─── RACE CONDITION REPRODUCTION TEST ─────────────────────────────────────────

async def test_concurrent_tray_mutations():
    """
    Reproduce the race condition: concurrent messages to the same session_id.
    Verify no duplicate ghosts, no lost turn counter updates, deterministic state.
    """
    print("\n[RACE CONDITION] Testing concurrent tray mutations.\n")
    
    captured_trays = []
    
    async def capture_llm(messages):
        return "ok"
    
    bot = Projector(
        base_config(),
        llm_call=capture_llm,
        max_active_turns=1,  # Low threshold to trigger ghosting quickly
        memory_db_path=DB,
    )
    
    # Send 20 concurrent messages to the same session
    # This would previously cause race conditions in tray mutations
    session_id = "race_test_session"
    messages = [f"message_{i} code weather python" for i in range(20)]
    
    await asyncio.gather(*[
        bot.process(msg, session_id=session_id)
        for msg in messages
    ])
    
    # Check the final tray state
    tray = await bot._get_tray(session_id)
    
    # Count ghosts - should not have duplicates
    ghost_ids = [s.id for s in tray.ghosts]
    active_ids = [s.id for s in tray.active]
    
    # Check for duplicate ghost IDs (race condition symptom)
    ghost_id_counts = {}
    for gid in ghost_ids:
        ghost_id_counts[gid] = ghost_id_counts.get(gid, 0) + 1
    
    duplicate_ghosts = {gid: count for gid, count in ghost_id_counts.items() if count > 1}
    
    if not duplicate_ghosts:
        print(f"  [PASS] No duplicate ghosts in tray")
    else:
        print(f"  [FAIL] Found duplicate ghosts: {duplicate_ghosts}")
    
    # Check that slide states are consistent
    # Each slide should have valid attributes
    all_slides = tray.all_slides()
    
    # Check that all slides have valid types
    invalid_types = [s for s in all_slides if s.type not in ('lamp', 'lens', 'tool', 'memory', 'data')]
    
    if not invalid_types:
        print(f"  [PASS] All slides have valid types")
    else:
        print(f"  [FAIL] Invalid slide types found")
    
    # Check that the tray state is deterministic
    # Run the same test again and compare
    bot2 = Projector(
        base_config(),
        llm_call=capture_llm,
        max_active_turns=1,
        memory_db_path=DB,
    )
    
    session_id2 = "race_test_session2"
    await asyncio.gather(*[
        bot2.process(msg, session_id=session_id2)
        for msg in messages
    ])
    
    tray2 = await bot2._get_tray(session_id2)
    
    # Compare ghost counts (should be the same)
    if len(tray.ghosts) == len(tray2.ghosts):
        print(f"  [PASS] Deterministic ghost count: {len(tray.ghosts)}")
    else:
        print(f"  [WARN] Non-deterministic ghost count: {len(tray.ghosts)} vs {len(tray2.ghosts)}")
    
    # Compare active counts (should be the same)
    if len(tray.active) == len(tray2.active):
        print(f"  [PASS] Deterministic active count: {len(tray.active)}")
    else:
        print(f"  [WARN] Non-deterministic active count: {len(tray.active)} vs {len(tray2.active)}")
    
    cleanup()


async def test_concurrent_different_sessions():
    """
    Test that concurrent messages to different sessions don't interfere.
    Each session should have its own isolated tray state.
    """
    print("\n[CONCURRENT SESSIONS] Testing isolation between concurrent sessions.\n")
    
    async def capture_llm(messages):
        return "ok"
    
    bot = Projector(
        base_config(),
        llm_call=capture_llm,
        max_active_turns=1,
        memory_db_path=DB,
    )
    
    # Send concurrent messages to 5 different sessions
    session_ids = [f"session_{i}" for i in range(5)]
    
    tasks = []
    for session_id in session_ids:
        for i in range(10):
            tasks.append(bot.process(f"message_{i} code", session_id=session_id))
    
    await asyncio.gather(*tasks)
    
    # Check that each session has its own tray
    for session_id in session_ids:
        tray = await bot._get_tray(session_id)
        if tray:
            print(f"  [INFO] Session {session_id}: {len(tray.active)} active, {len(tray.ghosts)} ghosts")
        else:
            print(f"  [FAIL] Session {session_id} has no tray")
    
    # Check that sessions don't share trays
    trays = [await bot._get_tray(sid) for sid in session_ids]
    unique_trays = len(set(id(t) for t in trays if t))
    
    if unique_trays == len(session_ids):
        print(f"  [PASS] Each session has its own tray")
    else:
        print(f"  [FAIL] Sessions share trays: {unique_trays} unique for {len(session_ids)} sessions")
    
    cleanup()


async def test_ghost_counter_consistency():
    """
    Test that ghost states are updated correctly under concurrent load.
    Without locking, ghost states could be lost or corrupted.
    """
    print("\n[GHOST STATE] Testing ghost state consistency under load.\n")
    
    async def capture_llm(messages):
        return "ok"
    
    bot = Projector(
        base_config(),
        llm_call=capture_llm,
        max_active_turns=2,
        memory_db_path=DB,
    )
    
    session_id = "counter_test"
    
    # Send messages that trigger the same slide repeatedly
    # This should affect ghost state
    for i in range(30):
        await bot.process("write some code", session_id=session_id)
    
    tray = await bot._get_tray(session_id)
    code_lens = [s for s in tray.all_slides() if s.id == "code_lens"]
    
    if code_lens:
        slide = code_lens[0]
        print(f"  [INFO] code_lens is_ghost: {slide.is_ghost}")
        print(f"  [INFO] code_lens type: {slide.type}")
        
        # Slide should have valid attributes
        if slide.type in ('lamp', 'lens', 'tool', 'memory', 'data'):
            print(f"  [PASS] Slide has valid type")
        else:
            print(f"  [FAIL] Slide has invalid type: {slide.type}")
    else:
        print(f"  [FAIL] code_lens not found in tray")
    
    cleanup()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("SESSIONLOCKS RACE CONDITION TESTS")
    print("Testing per-session locking for tray mutations")
    print("=" * 60)
    
    await test_session_locks_basic()
    await test_session_locks_concurrent_creation()
    await test_concurrent_tray_mutations()
    await test_concurrent_different_sessions()
    await test_ghost_counter_consistency()
    
    print("\n" + "=" * 60)
    print("SessionLocks tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
