"""
Base interface for academic platform adapters.
"""
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

from core.http_client import AcademicHttpClient, SessionStore


class AcademicPlatform(ABC):
    """Abstract base class for academic database integrations."""

    def __init__(self, name: str):
        self.name = name.lower()
        self.http_client_factory = AcademicHttpClient(self.name)

    @property
    def session_config(self) -> Dict[str, Any]:
        return SessionStore.get_session(self.name)

    @abstractmethod
    def search(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """
        Executes search on the database.
        Returns:
            {
                "total_results": int,
                "page": int,
                "page_size": int,
                "papers": List[Dict[str, Any]],
                "query_used": str
            }
        """
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Tests whether the current session/credentials are valid.
        Returns:
            {
                "database": str,
                "connected": bool,
                "status_code": Optional[int],
                "message": str
            }
        """
        pass

    @abstractmethod
    def get_paper_count(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
    ) -> int:
        """Returns total hit count for a query without downloading full papers."""
        pass
