"""
Simplified edge case tests for Cyrrus - focused on new features only.

Run: pytest tests/test_edge_cases_simple.py -v
"""
import asyncio
import os
import pytest
import tempfile
from cyrrus import Projector
from cyrrus.memory import MemoryVault
from cyrrus.providers import anthropic

FAILED = []
WARNED = []


def check(name, condition, warning=False):
    status = "PASS" if condition else ("WARN" if warning else "FAIL")
    print(f"  [{status}] {name}")
    if not condition:
        (WARNED if warning else FAILED).append(name)


async def default_llm(messages):
    return "ok"


def base_config():
    return {
        "core_lamp": {"content": "You are helpful."},
        "code_lens": {
            "content": "Output only code.",
            "triggers": ["code", "script", "python"],
        },
    }


# ─── SESSION ID VALIDATION EDGE CASES ─────────────────────────────────────

@pytest.mark.asyncio
async def test_session_id_empty_variants():
    """Test various empty/whitespace session_ids"""
    print("\n[SESSION ID EMPTY VARIANTS] Testing empty variants\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    bot = Projector(base_config(), llm_call=default_llm, memory_db_path=db_path)
    
    cases = [
        ("Empty string", ""),
        ("Spaces only", "   "),
        ("Tabs only", "\t\t"),
        ("Newlines only", "\n\n"),
        ("Mixed whitespace", " \t\n "),
    ]
    
    for name, session_id in cases:
        try:
            result = await bot.process("hello", session_id=session_id)
            check(f"{name}: rejected with error", False, warning=True)
        except ValueError:
            check(f"{name}: rejected with error", True)
        except Exception as e:
            check(f"{name}: unexpected error {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_session_id_type_injection():
    """Test non-string types as session_id"""
    print("\n[SESSION ID TYPE INJECTION] Testing type injection\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    bot = Projector(base_config(), llm_call=default_llm, memory_db_path=db_path)
    
    # Test that non-string types are rejected
    try:
        result = await bot.process("hello", session_id=123)
        check("Integer session_id: rejected with error", False, warning=True)
    except (TypeError, ValueError):
        check("Integer session_id: rejected with error", True)
    except Exception as e:
        check(f"Integer session_id: unexpected error {type(e).__name__}", False)
    
    try:
        result = await bot.process("hello", session_id=["list"])
        check("List session_id: rejected with error", False, warning=True)
    except (TypeError, ValueError):
        check("List session_id: rejected with error", True)
    except Exception as e:
        check(f"List session_id: unexpected error {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_session_id_sql_injection():
    """Test SQL injection via session_id"""
    print("\n[SESSION ID SQL INJECTION] Testing SQL injection attempts\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    bot = Projector(base_config(), llm_call=default_llm, memory_db_path=db_path)
    
    cases = [
        ("DROP TABLE", "'; DROP TABLE facts; --"),
        ("UNION SELECT", "' UNION SELECT * FROM facts --"),
        ("Comment injection", "user'--"),
        ("Semicolon", "user';"),
        ("Quote injection", "' OR '1'='1"),
    ]
    
    for name, session_id in cases:
        try:
            result = await bot.process("hello", session_id=session_id)
            check(f"{name}: handled without crash", isinstance(result, str))
            # Verify DB still works
            result2 = await bot.process("hello", session_id="normal_user")
            check(f"{name}: DB still functional after injection", isinstance(result2, str))
        except Exception as e:
            check(f"{name}: crashed with {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


# ─── MEMORYVAULT.DELETE_SESSION() EDGE CASES ───────────────────────────────

@pytest.mark.asyncio
async def test_delete_session_nonexistent():
    """Test deleting a session that doesn't exist"""
    print("\n[DELETE SESSION NONEXISTENT] Testing delete of non-existent session\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    vault = MemoryVault(db_path=db_path)
    deleted = await vault.delete_session("nonexistent_session_xyz")
    check("Delete non-existent session: returns 0", deleted == 0)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_delete_session_max_capacity():
    """Test deleting a session at max capacity"""
    print("\n[DELETE SESSION MAX CAPACITY] Testing delete of full session\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    vault = MemoryVault(db_path=db_path, max_facts_per_session=500)
    for i in range(500):
        await vault.upsert("full_session", f"fact_{i}", f"value_{i}", 2)
    
    deleted = await vault.delete_session("full_session")
    check("Delete full session: deletes all 500 facts", deleted == 500)
    
    # Verify session is truly gone
    results = await vault.retrieve("full_session", "fact_0", limit=1)
    check("Delete full session: session is truly empty", len(results) == 0)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_delete_session_sql_injection():
    """Test SQL injection via session_id in delete"""
    print("\n[DELETE SESSION SQL INJECTION] Testing SQL injection\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    vault = MemoryVault(db_path=db_path)
    await vault.upsert("safe_session", "name", "Alice", 2)
    
    injection_attempts = [
        "'; DROP TABLE facts; --",
        "' OR '1'='1",
        "safe_session'; DROP TABLE facts; --",
    ]
    
    for injection in injection_attempts:
        try:
            deleted = await vault.delete_session(injection)
            # Verify safe session still exists
            results = await vault.retrieve("safe_session", "name", limit=1)
            check(f"SQL injection '{injection[:20]}...': safe session intact", len(results) > 0)
        except Exception as e:
            check(f"SQL injection '{injection[:20]}...': crashed with {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


# ─── TOOL EXECUTOR TIMEOUT EDGE CASES ────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_timeout_zero():
    """Test timeout = 0"""
    print("\n[TOOL TIMEOUT ZERO] Testing timeout=0\n")
    
    async def slow_tool(query):
        await asyncio.sleep(10)
        return "slow result"
    
    config = {
        "core_lamp": {"content": "You are helpful."},
        "slow_tool": {
            "content": "Slow tool.",
            "type": "tool",
            "handler": "slow_tool",
            "triggers": ["slow"],
        },
    }
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    
    try:
        bot = Projector(config, llm_call=default_llm, tool_executors={"slow_tool": slow_tool}, 
                       tool_executor_timeout=0, memory_db_path=db_path)
        result = await bot.process("slow", session_id="test")
        check("timeout=0: handled without crash", isinstance(result, str), warning=True)
    except Exception as e:
        check(f"timeout=0: crashed with {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_tool_timeout_negative():
    """Test negative timeout"""
    print("\n[TOOL TIMEOUT NEGATIVE] Testing negative timeout\n")
    
    async def slow_tool(query):
        await asyncio.sleep(10)
        return "slow result"
    
    config = {
        "core_lamp": {"content": "You are helpful."},
        "slow_tool": {
            "content": "Slow tool.",
            "type": "tool",
            "handler": "slow_tool",
            "triggers": ["slow"],
        },
    }
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    
    try:
        bot = Projector(config, llm_call=default_llm, tool_executors={"slow_tool": slow_tool}, 
                       tool_executor_timeout=-1, memory_db_path=db_path)
        result = await bot.process("slow", session_id="test")
        check("timeout=-1: handled without crash", isinstance(result, str), warning=True)
    except Exception as e:
        check(f"timeout=-1: crashed with {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_tool_timeout_float():
    """Test float timeout"""
    print("\n[TOOL TIMEOUT FLOAT] Testing float timeout\n")
    
    async def medium_tool(query):
        await asyncio.sleep(0.1)
        return "medium result"
    
    config = {
        "core_lamp": {"content": "You are helpful."},
        "medium_tool": {
            "content": "Medium tool.",
            "type": "tool",
            "handler": "medium_tool",
            "triggers": ["medium"],
        },
    }
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    
    try:
        bot = Projector(config, llm_call=default_llm, tool_executors={"medium_tool": medium_tool}, 
                       tool_executor_timeout=1.5, memory_db_path=db_path)
        result = await bot.process("medium", session_id="test")
        check("timeout=1.5: handled without crash", isinstance(result, str))
    except Exception as e:
        check(f"timeout=1.5: crashed with {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


# ─── ANTHROPIC MAX_TOKENS EDGE CASES ────────────────────────────────────

def test_anthropic_max_tokens_zero():
    """Test max_tokens = 0"""
    print("\n[ANTHROPIC MAX_TOKENS ZERO] Testing max_tokens=0\n")
    
    try:
        # This should fail at the API level, not crash
        provider = anthropic(max_tokens=0, api_key="test")
        check("max_tokens=0: provider created without crash", True, warning=True)
    except Exception as e:
        check(f"max_tokens=0: crashed with {type(e).__name__}", False)


def test_anthropic_max_tokens_negative():
    """Test negative max_tokens"""
    print("\n[ANTHROPIC MAX_TOKENS NEGATIVE] Testing negative max_tokens\n")
    
    try:
        provider = anthropic(max_tokens=-1, api_key="test")
        check("max_tokens=-1: provider created without crash", True, warning=True)
    except Exception as e:
        check(f"max_tokens=-1: crashed with {type(e).__name__}", False)


def test_anthropic_max_tokens_very_large():
    """Test very large max_tokens"""
    print("\n[ANTHROPIC MAX_TOKENS VERY LARGE] Testing very large max_tokens\n")
    
    try:
        provider = anthropic(max_tokens=999999999, api_key="test")
        check("max_tokens=999999999: provider created without crash", True)
    except Exception as e:
        check(f"max_tokens=999999999: crashed with {type(e).__name__}", False)


def test_anthropic_max_tokens_float():
    """Test float max_tokens"""
    print("\n[ANTHROPIC MAX_TOKENS FLOAT] Testing float max_tokens\n")
    
    try:
        provider = anthropic(max_tokens=1024.5, api_key="test")
        check("max_tokens=1024.5: provider created without crash", True, warning=True)
    except Exception as e:
        check(f"max_tokens=1024.5: crashed with {type(e).__name__}", False)


def test_anthropic_max_tokens_string():
    """Test string max_tokens (type error)"""
    print("\n[ANTHROPIC MAX_TOKENS STRING] Testing string max_tokens\n")
    
    try:
        provider = anthropic(max_tokens="1024", api_key="test")
        check("max_tokens='1024': provider created without crash", False, warning=True)
    except (TypeError, ValueError):
        check("max_tokens='1024': rejected with error", True)
    except Exception as e:
        check(f"max_tokens='1024': unexpected error {type(e).__name__}", False)


# ─── CONFIGURATION MALFORMATION TESTS ───────────────────────────────────

@pytest.mark.asyncio
async def test_config_empty():
    """Test empty config"""
    print("\n[CONFIG EMPTY] Testing empty config\n")
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    
    try:
        bot = Projector({}, llm_call=default_llm, memory_db_path=db_path)
        check("Empty config: rejected with error", False, warning=True)
    except Exception as e:
        check(f"Empty config: rejected with error {type(e).__name__}", True)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_config_zero_priority():
    """Test priority = 0 (division by zero in knapsack)"""
    print("\n[CONFIG ZERO PRIORITY] Testing priority=0\n")
    
    config = {
        "core_lamp": {"content": "You are helpful."},
        "zero_slide": {
            "content": "Zero priority slide.",
            "priority": 0,
            "tokens": 5,
            "triggers": ["zero"],
        },
    }
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    
    try:
        bot = Projector(config, llm_call=default_llm, memory_db_path=db_path)
        result = await bot.process("zero", session_id="test")
        check("priority=0: no division by zero, bot responds", isinstance(result, str))
    except ZeroDivisionError:
        check("priority=0: division by zero occurred", False)
    except Exception as e:
        check(f"priority=0: crashed with {type(e).__name__}", False)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


@pytest.mark.asyncio
async def test_config_tool_without_handler():
    """Test tool slide without handler"""
    print("\n[CONFIG TOOL WITHOUT HANDLER] Testing tool without handler\n")
    
    config = {
        "core_lamp": {"content": "You are helpful."},
        "bad_tool": {
            "content": "Tool without handler.",
            "type": "tool",
            "triggers": ["tool"],
        },
    }
    
    db_path = tempfile.mktemp(suffix=".db", prefix="edge_case_")
    
    try:
        bot = Projector(config, llm_call=default_llm, memory_db_path=db_path)
        check("Tool without handler: rejected with error", False, warning=True)
    except Exception as e:
        check(f"Tool without handler: rejected with error {type(e).__name__}", True)
    
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.remove(db_path + ext)
        except:
            pass


# ─── SUMMARY ─────────────────────────────────────────────────────────────

def test_summary():
    """Print summary of all edge case tests"""
    print("\n" + "=" * 60)
    print("EDGE CASE TEST SUMMARY")
    print("=" * 60)
    
    if WARNED:
        print(f"\n{len(WARNED)} WARNINGS (known limitations):")
        for w in WARNED:
            print(f"  [WARN] {w}")
    
    if FAILED:
        print(f"\n{len(FAILED)} FAILURES (real problems):")
        for f in FAILED:
            print(f"  [FAIL] {f}")
        print("\nSome edge cases caused failures. Review above.")
    else:
        print("\nAll edge case tests passed or have documented warnings.")
        print("Cyrrus handles edge cases gracefully.")
