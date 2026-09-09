"""
Abstract backend interface for MemoryVault storage.

This allows pluggable storage backends (SQLite, Postgres, Redis, etc.)
while keeping MemoryVault backend-agnostic.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
import asyncio


class MemoryBackend(ABC):
    """
    Abstract interface for memory storage backends.
    
    All storage backends must implement these methods to provide
    the core operations that MemoryVault requires.
    """
    
    @abstractmethod
    async def init_db(self) -> None:
        """
        Initialize the storage backend.
        Create tables, indexes, and perform any necessary migrations.
        """
        pass
    
    @abstractmethod
    async def upsert(
        self,
        session_id: str,
        keyword: str,
        value: str,
        tokens: int,
        max_facts_per_session: int,
        max_fact_value_length: int
    ) -> None:
        """
        Store or update a fact for a session.
        
        For temporal memory, this should:
        - Invalidate any existing current fact for (session_id, keyword)
        - Insert the new fact as current with valid_at timestamp
        
        Args:
            session_id: The session identifier
            keyword: The fact keyword
            value: The fact value
            tokens: Estimated token count
            max_facts_per_session: Maximum current facts per session (for pruning)
            max_fact_value_length: Maximum length for fact values (for truncation)
        """
        pass
    
    @abstractmethod
    async def retrieve_current(self, session_id: str, limit: int = 100) -> List[tuple]:
        """
        Retrieve current facts for a session (invalid_at IS NULL).
        
        Args:
            session_id: The session identifier
            limit: Maximum number of facts to retrieve
            
        Returns:
            List of tuples: (keyword, value, tokens)
        """
        pass
    
    @abstractmethod
    async def touch(self, session_id: str, keywords: List[str]) -> None:
        """
        Update last_accessed timestamp for specified facts.
        
        Args:
            session_id: The session identifier
            keywords: List of keywords to touch
        """
        pass
    
    @abstractmethod
    async def delete_session(self, session_id: str) -> int:
        """
        Delete all facts for a session.
        
        Args:
            session_id: The session identifier
            
        Returns:
            Number of facts deleted
        """
        pass
    
    @abstractmethod
    async def get_fact_history(
        self,
        session_id: str,
        keyword: str
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the full timeline of a fact.
        
        Args:
            session_id: The session identifier
            keyword: The fact keyword
            
        Returns:
            List of dicts with keys: value, tokens, valid_at, invalid_at
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections or cleanup resources.
        """
        pass
