"""
Central SQLite database layer for MCPCONECCT.
Stores agent search history, query iterations, persistent sessions, and export records.
"""
from typing import Dict, Any, List, Optional
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from config import settings

DB_PATH = settings.BASE_DIR / "data" / "mcpconecct.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes tables if they do not exist."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Search History (Audit trail of every call by Codex, Claude, Antigravity or Web UI)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            database TEXT NOT NULL,
            search_mode TEXT NOT NULL,
            query TEXT NOT NULL,
            filters_json TEXT,
            total_hits INTEGER DEFAULT 0,
            execution_time_ms INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            error_message TEXT,
            bibtex_file TEXT,
            csv_file TEXT
        )
        """)

        # 2. Query Iterations (PICO components, version history, notes, calibration probe counts)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            title TEXT NOT NULL,
            version TEXT NOT NULL,
            pico_json TEXT,
            canonical_query TEXT NOT NULL,
            notes TEXT,
            counts_json TEXT
        )
        """)

        # 3. Platform Sessions (Auth credentials, cookies, headers, status)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS platform_sessions (
            database TEXT PRIMARY KEY,
            auth_type TEXT,
            status TEXT,
            last_tested TEXT,
            cookies_json TEXT,
            headers_json TEXT,
            api_key TEXT
        )
        """)

        # 4. Exports Registry
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS exports_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            filename TEXT NOT NULL,
            format TEXT NOT NULL,
            database TEXT NOT NULL,
            record_count INTEGER DEFAULT 0,
            file_path TEXT NOT NULL
        )
        """)

        conn.commit()


# Initialize on import
init_db()


# --- Search History CRUD ---

def record_search(
    agent_name: str,
    database: str,
    query: str,
    search_mode: str = "advanced",
    filters: Optional[Dict[str, Any]] = None,
    total_hits: int = 0,
    execution_time_ms: int = 0,
    status: str = "success",
    error_message: Optional[str] = None,
    bibtex_file: Optional[str] = None,
    csv_file: Optional[str] = None,
) -> int:
    """Records an execution event into search_history."""
    timestamp = datetime.now().isoformat()
    filters_json = json.dumps(filters or {})

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO search_history (
            timestamp, agent_name, database, search_mode, query,
            filters_json, total_hits, execution_time_ms, status,
            error_message, bibtex_file, csv_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, agent_name, database.lower(), search_mode.lower(),
            query, filters_json, total_hits, execution_time_ms, status,
            error_message, bibtex_file, csv_file
        ))
        conn.commit()
        return cursor.lastrowid


def get_search_history(limit: int = 50, database: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves recent search executions."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if database:
            cursor.execute(
                "SELECT * FROM search_history WHERE database = ? ORDER BY id DESC LIMIT ?",
                (database.lower(), limit)
            )
        else:
            cursor.execute("SELECT * FROM search_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d["filters"] = json.loads(d["filters_json"] or "{}")
            results.append(d)
        return results


# --- Query Iterations CRUD ---

def save_query_iteration(
    title: str,
    version: str,
    canonical_query: str,
    pico_data: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    counts: Optional[Dict[str, Any]] = None,
) -> int:
    timestamp = datetime.now().isoformat()
    pico_json = json.dumps(pico_data or {})
    counts_json = json.dumps(counts or {})

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO query_iterations (
            timestamp, title, version, pico_json, canonical_query, notes, counts_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, title, version, pico_json, canonical_query, notes, counts_json))
        conn.commit()
        return cursor.lastrowid


def get_query_iterations() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM query_iterations ORDER BY id DESC")
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["pico"] = json.loads(d["pico_json"] or "{}")
            d["counts"] = json.loads(d["counts_json"] or "{}")
            results.append(d)
        return results


# --- Exports Registry CRUD ---

def record_export(
    filename: str,
    format_type: str,
    database: str,
    record_count: int,
    file_path: str,
) -> int:
    timestamp = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO exports_registry (timestamp, filename, format, database, record_count, file_path)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (timestamp, filename, format_type, database.lower(), record_count, str(file_path)))
        conn.commit()
        return cursor.lastrowid


def get_exports(limit: int = 50) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM exports_registry ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]
