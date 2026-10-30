"""
Query Cache Manager for MCPCONECCT.
Provides canonical SHA-256 hashing and SQLite-backed persistent caching with 48h TTL.
"""
from typing import Dict, Any, List, Optional
import hashlib
import json
from datetime import datetime, timedelta

from core.db import get_connection


class QueryCacheManager:
    """Manages multi-database query response caching to avoid redundant external network requests."""

    @staticmethod
    def compute_hash(
        database: str,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> str:
        """Computes a deterministic SHA-256 hash for query parameters."""
        normalized_query = " ".join(query.strip().lower().split())
        doc_types_sorted = sorted(doc_types) if doc_types else []
        
        canonical_payload = {
            "db": database.strip().lower(),
            "q": normalized_query,
            "ys": year_start,
            "ye": year_end,
            "dt": doc_types_sorted,
            "p": page,
            "ps": page_size,
        }
        raw_json = json.dumps(canonical_payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    @classmethod
    def get_cached_page(
        cls,
        query_hash: str,
        ttl_hours: int = 48
    ) -> Optional[Dict[str, Any]]:
        """Retrieves cached response JSON if still within TTL."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT response_json, created_at,
                   ((julianday('now') - julianday(created_at)) * 24.0) AS age_hours
            FROM query_cache
            WHERE query_hash = ?
            """, (query_hash,))
            row = cursor.fetchone()
            if not row:
                return None
            
            age_hours = row["age_hours"]
            if age_hours is not None and age_hours > ttl_hours:
                # Expired
                return None
            
            try:
                return json.loads(row["response_json"])
            except Exception:
                return None

    @classmethod
    def set_cached_page(
        cls,
        query_hash: str,
        database: str,
        query: str,
        response_data: Dict[str, Any],
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 25,
        total_hits: int = 0,
    ) -> None:
        """Stores or replaces a query response page into the cache."""
        normalized_query = " ".join(query.strip().lower().split())
        doc_types_json = json.dumps(sorted(doc_types) if doc_types else [])
        response_json = json.dumps(response_data)

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO query_cache (
                query_hash, database_name, normalized_query,
                year_start, year_end, doc_types_json,
                page, page_size, total_hits, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                query_hash, database.strip().lower(), normalized_query,
                year_start, year_end, doc_types_json,
                page, page_size, total_hits, response_json
            ))
            conn.commit()

    @classmethod
    def clear_expired_cache(cls, ttl_hours: int = 48) -> int:
        """Removes all cache entries older than the specified TTL."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            DELETE FROM query_cache
            WHERE ((julianday('now') - julianday(created_at)) * 24.0) > ?
            """, (ttl_hours,))
            conn.commit()
            return cursor.rowcount
