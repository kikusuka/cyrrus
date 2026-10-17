"""
Tests for pluggable memory backend interface.
"""
import pytest
import asyncio
from typing import List, Dict, Any

from cyrrus.backend import MemoryBackend
from cyrrus.sqlite_backend import SQLiteBackend
from cyrrus.memory import MemoryVault
from cyrrus import Projector


class MockBackend(MemoryBackend):
    """Mock backend for testing pluggable interface."""
    
    def __init__(self):
        self.facts = {}  # {(session_id, keyword): (value, tokens, valid_at, invalid_at)}
        self.initialized = False
        self.closed = False
    
    async def init_db(self) -> None:
        self.initialized = True
    
    async def upsert(
        self,
        session_id: str,
        keyword: str,
        value: str,
        tokens: int,
        max_facts_per_session: int,
        max_fact_value_length: int
    ) -> None:
        # Truncate if needed
        if value and len(value) > max_fact_value_length:
            value = value[:max_fact_value_length].rsplit(" ", 1)[0] + "..."
            tokens = min(tokens, len(value.split()))
        
        # Invalidate old fact
        key = (session_id, keyword)
        if key in self.facts:
            old_val, old_tok, valid_at, _ = self.facts[key]
            self.facts[key] = (value, tokens, valid_at, "invalidated")
        else:
            import datetime
            self.facts[key] = (value, tokens, datetime.datetime.now().isoformat(), None)
    
    async def retrieve_current(self, session_id: str, limit: int = 100) -> List[tuple]:
        results = []
        for (sid, kw), (val, tok, valid_at, invalid_at) in self.facts.items():
            if sid == session_id and invalid_at is None:
                results.append((kw, val, tok))
        return results[:limit]
    
    async def touch(self, session_id: str, keywords: List[str]) -> None:
        # Mock implementation - no-op
        pass
    
    async def delete_session(self, session_id: str) -> int:
        count = 0
        keys_to_delete = []
        for (sid, kw) in self.facts.keys():
            if sid == session_id:
                keys_to_delete.append((sid, kw))
                count += 1
        for key in keys_to_delete:
            del self.facts[key]
        return count
    
    async def get_fact_history(
        self,
        session_id: str,
        keyword: str
    ) -> List[Dict[str, Any]]:
        key = (session_id, keyword)
        if key in self.facts:
            val, tok, valid_at, invalid_at = self.facts[key]
            return [{
                "value": val,
                "tokens": tok,
                "valid_at": valid_at,
                "invalid_at": invalid_at,
            }]
        return []
    
    async def close(self) -> None:
        self.closed = True


class TestMemoryBackendInterface:
    """Test that the backend interface is properly defined."""
    
    def test_backend_is_abstract(self):
        """Test that MemoryBackend cannot be instantiated directly."""
        with pytest.raises(TypeError):
            MemoryBackend()
    
    @pytest.mark.asyncio
    async def test_mock_backend_implements_interface(self):
        """Test that mock backend implements all required methods."""
        backend = MockBackend()
        
        await backend.init_db()
        assert backend.initialized
        
        await backend.upsert("session1", "test_key", "test_value", 5, 100, 500)
        
        results = await backend.retrieve_current("session1")
        assert len(results) == 1
        assert results[0] == ("test_key", "test_value", 5)
        
        await backend.touch("session1", ["test_key"])
        
        history = await backend.get_fact_history("session1", "test_key")
        assert len(history) == 1
        
        count = await backend.delete_session("session1")
        assert count == 1
        
        await backend.close()
        assert backend.closed


class TestSQLiteBackend:
    """Test SQLite backend implementation."""
    
    @pytest.mark.asyncio
    async def test_sqlite_backend_initialization(self):
        """Test that SQLite backend initializes correctly."""
        backend = SQLiteBackend(":memory:")
        await backend.init_db()
        assert backend._initialized
        await backend.close()
    
    @pytest.mark.asyncio
    async def test_sqlite_backend_upsert_and_retrieve(self):
        """Test basic upsert and retrieve operations."""
        backend = SQLiteBackend(":memory:")
        await backend.init_db()
        
        await backend.upsert("session1", "user_name", "Alice", 1, 100, 500)
        
        results = await backend.retrieve_current("session1")
        assert len(results) == 1
        assert results[0] == ("user_name", "Alice", 1)
        
        await backend.close()
    
    @pytest.mark.asyncio
    async def test_sqlite_backend_temporal_tracking(self):
        """Test that temporal tracking (invalid_at) works correctly."""
        backend = SQLiteBackend(":memory:")
        await backend.init_db()
        
        # Insert initial fact
        await backend.upsert("session1", "user_name", "Alice", 1, 100, 500)
        
        # Update the fact
        await backend.upsert("session1", "user_name", "Bob", 1, 100, 500)
        
        # Only current fact should be retrieved
        results = await backend.retrieve_current("session1")
        assert len(results) == 1
        assert results[0] == ("user_name", "Bob", 1)
        
        # History should show both versions
        history = await backend.get_fact_history("session1", "user_name")
        assert len(history) == 2
        assert history[0]["value"] == "Alice"
        assert history[1]["value"] == "Bob"
        
        await backend.close()
    
    @pytest.mark.asyncio
    async def test_sqlite_backend_session_isolation(self):
        """Test that sessions are properly isolated."""
        backend = SQLiteBackend(":memory:")
        await backend.init_db()
        
        await backend.upsert("session1", "user_name", "Alice", 1, 100, 500)
        await backend.upsert("session2", "user_name", "Bob", 1, 100, 500)
        
        results1 = await backend.retrieve_current("session1")
        results2 = await backend.retrieve_current("session2")
        
        assert len(results1) == 1
        assert results1[0][1] == "Alice"
        assert len(results2) == 1
        assert results2[0][1] == "Bob"
        
        await backend.close()
    
    @pytest.mark.asyncio
    async def test_sqlite_backend_delete_session(self):
        """Test session deletion."""
        backend = SQLiteBackend(":memory:")
        await backend.init_db()
        
        await backend.upsert("session1", "user_name", "Alice", 1, 100, 500)
        await backend.upsert("session1", "user_project", "cyrrus", 2, 100, 500)
        
        count = await backend.delete_session("session1")
        assert count == 2
        
        results = await backend.retrieve_current("session1")
        assert len(results) == 0
        
        await backend.close()


class TestMemoryVaultWithBackend:
    """Test MemoryVault with pluggable backends."""
    
    @pytest.mark.asyncio
    async def test_memoryvault_uses_sqlite_backend_by_default(self):
        """Test that MemoryVault uses SQLiteBackend by default."""
        memory = MemoryVault(db_path=":memory:")
        
        await memory.upsert("session1", "user_name", "Alice", 1)
        
        results = await memory.retrieve("session1", "what's my name")
        assert len(results) == 1
        assert "Alice" in results[0].content
        
        # Clean up
        await memory.delete_session("session1")
    
    @pytest.mark.asyncio
    async def test_memoryvault_uses_custom_backend(self):
        """Test that MemoryVault can use a custom backend."""
        mock_backend = MockBackend()
        memory = MemoryVault(backend=mock_backend)
        
        await memory.upsert("session1", "user_name", "Alice", 1)
        
        # Verify the mock backend was used
        assert ("session1", "user_name") in mock_backend.facts
        
        results = await memory.retrieve("session1", "what's my name")
        assert len(results) == 1
        assert "Alice" in results[0].content
    
    @pytest.mark.asyncio
    async def test_memoryvault_delegates_to_backend(self):
        """Test that MemoryVault correctly delegates all operations to backend."""
        mock_backend = MockBackend()
        memory = MemoryVault(backend=mock_backend)
        
        # Test upsert
        await memory.upsert("session1", "test_key", "test_value", 5)
        assert ("session1", "test_key") in mock_backend.facts
        
        # Test retrieve
        results = await memory.retrieve("session1", "test")
        assert len(results) == 1
        
        # Test delete_session
        count = await memory.delete_session("session1")
        assert count == 1
        assert ("session1", "test_key") not in mock_backend.facts
        
        # Test get_fact_history
        await memory.upsert("session1", "test_key", "value1", 5)
        await memory.upsert("session1", "test_key", "value2", 5)
        history = await memory.get_fact_history("session1", "test_key")
        assert len(history) >= 1


class TestBackwardCompatibility:
    """Test that the refactor maintains backward compatibility."""
    
    @pytest.mark.asyncio
    async def test_sqlite_backend_identical_to_original(self):
        """Test that SQLiteBackend produces identical behavior to original."""
        # Test with SQLite backend
        memory_sqlite = MemoryVault(db_path=":memory:")
        
        await memory_sqlite.upsert("session1", "user_name", "Alice", 1)
        await memory_sqlite.upsert("session1", "user_project", "cyrrus", 2)
        
        results = await memory_sqlite.retrieve("session1", "what's my name and project")
        assert len(results) >= 1
        
        # Test temporal tracking
        await memory_sqlite.upsert("session1", "user_name", "Bob", 1)
        results = await memory_sqlite.retrieve("session1", "what's my name")
        assert "Bob" in results[0].content
        
        # Test history
        history = await memory_sqlite.get_fact_history("session1", "user_name")
        assert len(history) == 2
        
        # Test delete
        count = await memory_sqlite.delete_session("session1")
        assert count >= 1
        
        results = await memory_sqlite.retrieve("session1", "anything")
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_db_path_parameter_still_works(self):
        """Test that db_path parameter still works with backend refactor."""
        memory = MemoryVault(db_path=":memory:")
        
        await memory.upsert("session1", "test", "value", 1)
        results = await memory.retrieve("session1", "test")
        assert len(results) == 1


def test_projector_builds_outside_event_loop():
    """Projector must be constructible outside a running event loop.

    On Python 3.9, asyncio.Lock() calls get_event_loop() at construction,
    so creating a Projector outside a running event loop raises
    RuntimeError: There is no current event loop.  The fix makes the
    asyncio primitives (SessionLocks._meta and SQLiteBackend._init_lock)
    lazy: they are created on first use inside an async method, never in
    __init__.

    NOTE: This machine runs Python 3.14, where asyncio.Lock() does not
    require a running event loop at construction, so this test cannot
    fail on old code locally.  It will be verified by CI on Python 3.9.
    """
    # Run and close an event loop so there is no current one afterward.
    asyncio.run(asyncio.sleep(0))
    asyncio.set_event_loop(None)

    async def echo_llm(messages):
        return "ok"

    config = {
        "core_lamp": {"content": "You are helpful."},
    }
    # Building a Projector (which creates SessionLocks and SQLiteBackend)
    # must not raise outside an event loop.
    p = Projector(config, llm_call=echo_llm, memory_db_path=":memory:")

    # One process() turn inside a fresh event loop must work.
    result = asyncio.run(p.process("hello", session_id="sync_test"))
    assert isinstance(result, str) and len(result) > 0
