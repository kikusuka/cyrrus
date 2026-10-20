"""
Abstract backend interface for MemoryVault storage.

This allows pluggable storage backends (SQLite, Postgres, Redis, etc.)
while keeping MemoryVault backend-agnostic.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
import asyncio


MAX_SESSION_ID_LENGTH = 256
MAX_KEYWORD_LENGTH = 256
MAX_FACT_VALUE_LENGTH = 2000


def validate_session_id(session_id: str) -> None:
    """Raise ValueError for empty or over-long session ids."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(
            "session_id cannot be empty or whitespace-only. "
            "Pass a unique identifier per user, e.g. str(user_id)."
        )
    if len(session_id) > MAX_SESSION_ID_LENGTH:
        raise ValueError(
            f"session_id too long: {len(session_id)} characters "
            f"(max {MAX_SESSION_ID_LENGTH})."
        )


def validate_keyword(keyword: str) -> None:
    """Raise ValueError for over-long fact keywords."""
    if isinstance(keyword, str) and len(keyword) > MAX_KEYWORD_LENGTH:
        raise ValueError(
            f"fact keyword too long: {len(keyword)} characters "
            f"(max {MAX_KEYWORD_LENGTH})."
        )


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
        max_facts_per_session: Optional[int],
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
            max_facts_per_session: Maximum facts per session (None = unlimited).
                When exceeded, oldest superseded facts are deleted first,
                then oldest active facts.
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

    async def forget_fact(self, session_id: str, key: str) -> bool:
        """
        Physically delete ALL rows for (session_id, key), including
        superseded versions.

        Args:
            session_id: The session identifier
            key: The fact keyword

        Returns:
            True if at least one row was deleted, False otherwise.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement forget_fact()"
        )

    async def forget_session(self, session_id: str) -> int:
        """
        Delete all facts for a session.

        Args:
            session_id: The session identifier

        Returns:
            Number of facts deleted.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement forget_session()"
        )

    async def export_facts(
        self, session_id: str, include_superseded: bool = False
    ) -> list[dict]:
        """
        Export facts for a session as JSON-serializable dicts.

        Args:
            session_id: The session identifier
            include_superseded: If True, include superseded (invalidated)
                versions; otherwise only current facts.

        Returns:
            List of dicts with keys: key, value, created (valid_at),
            invalid_at. Ordered by creation (valid_at).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement export_facts()"
        )
