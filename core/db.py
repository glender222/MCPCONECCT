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
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
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

        # 5. Query Cache (SHA-256 canonical query hash with 48h TTL)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_cache (
            query_hash TEXT PRIMARY KEY,
            database_name TEXT NOT NULL,
            normalized_query TEXT NOT NULL,
            year_start INTEGER,
            year_end INTEGER,
            doc_types_json TEXT,
            page INTEGER NOT NULL DEFAULT 1,
            page_size INTEGER NOT NULL DEFAULT 25,
            total_hits INTEGER NOT NULL DEFAULT 0,
            response_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 6. Central Corpus Papers (Clean deduplicated research papers repository)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS corpus_papers (
            record_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL DEFAULT 'default_slr',
            doi TEXT,
            normalized_title TEXT NOT NULL,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            year INTEGER,
            venue TEXT,
            doc_type TEXT NOT NULL DEFAULT 'other',
            abstract TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            url TEXT NOT NULL DEFAULT '',
            sources_json TEXT NOT NULL DEFAULT '[]',
            raw_bibtex_key TEXT NOT NULL DEFAULT '',
            duplicate_count INTEGER NOT NULL DEFAULT 1,
            is_enriched_by_doi BOOLEAN NOT NULL DEFAULT 0,
            prisma_stage TEXT NOT NULL DEFAULT 'identification',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_corpus_doi ON corpus_papers(doi)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_corpus_norm_title ON corpus_papers(normalized_title)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_corpus_project ON corpus_papers(project_id)")

        # 7. Ingestion Jobs (Real-time tracking of bulk streaming fetches)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            job_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL DEFAULT 'default_slr',
            database_name TEXT NOT NULL,
            query TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            total_expected INTEGER DEFAULT 0,
            fetched_count INTEGER DEFAULT 0,
            enriched_count INTEGER DEFAULT 0,
            deduplicated_count INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


# --- Corpus Papers CRUD ---

def upsert_corpus_paper(paper_data: Dict[str, Any]) -> str:
    """Inserts or updates a canonical paper in corpus_papers."""
    record_id = paper_data.get("record_id", "")
    if not record_id:
        raise ValueError("record_id is required to upsert into corpus_papers")

    project_id = paper_data.get("project_id", "default_slr")
    doi = paper_data.get("doi")
    normalized_title = paper_data.get("normalized_title", "")
    title = paper_data.get("title", "")
    
    authors = paper_data.get("authors", [])
    authors_json = authors if isinstance(authors, str) else json.dumps(authors or [])
    
    year = paper_data.get("year")
    venue = paper_data.get("venue")
    doc_type = paper_data.get("doc_type", "other")
    abstract = paper_data.get("abstract", "") or ""
    
    keywords = paper_data.get("keywords", [])
    keywords_json = keywords if isinstance(keywords, str) else json.dumps(keywords or [])
    
    url = paper_data.get("url", "") or ""
    
    sources = paper_data.get("sources", [])
    sources_json = sources if isinstance(sources, str) else json.dumps(sources or [])
    
    raw_bibtex_key = paper_data.get("raw_bibtex_key", "") or ""
    duplicate_count = paper_data.get("duplicate_count", 1)
    is_enriched_by_doi = 1 if paper_data.get("is_enriched_by_doi") else 0
    prisma_stage = paper_data.get("prisma_stage", "identification")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO corpus_papers (
            record_id, project_id, doi, normalized_title, title,
            authors_json, year, venue, doc_type, abstract,
            keywords_json, url, sources_json, raw_bibtex_key,
            duplicate_count, is_enriched_by_doi, prisma_stage, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(record_id) DO UPDATE SET
            project_id = excluded.project_id,
            doi = COALESCE(excluded.doi, corpus_papers.doi),
            normalized_title = CASE WHEN excluded.normalized_title != '' THEN excluded.normalized_title ELSE corpus_papers.normalized_title END,
            title = CASE WHEN excluded.title != '' THEN excluded.title ELSE corpus_papers.title END,
            authors_json = CASE WHEN length(excluded.authors_json) > length(corpus_papers.authors_json) THEN excluded.authors_json ELSE corpus_papers.authors_json END,
            year = COALESCE(excluded.year, corpus_papers.year),
            venue = COALESCE(excluded.venue, corpus_papers.venue),
            doc_type = CASE WHEN excluded.doc_type != 'other' THEN excluded.doc_type ELSE corpus_papers.doc_type END,
            abstract = CASE WHEN length(excluded.abstract) > length(corpus_papers.abstract) THEN excluded.abstract ELSE corpus_papers.abstract END,
            keywords_json = CASE WHEN length(excluded.keywords_json) > length(corpus_papers.keywords_json) THEN excluded.keywords_json ELSE corpus_papers.keywords_json END,
            url = CASE WHEN excluded.url != '' THEN excluded.url ELSE corpus_papers.url END,
            sources_json = excluded.sources_json,
            raw_bibtex_key = CASE WHEN excluded.raw_bibtex_key != '' THEN excluded.raw_bibtex_key ELSE corpus_papers.raw_bibtex_key END,
            duplicate_count = corpus_papers.duplicate_count + 1,
            is_enriched_by_doi = MAX(corpus_papers.is_enriched_by_doi, excluded.is_enriched_by_doi),
            prisma_stage = excluded.prisma_stage,
            updated_at = CURRENT_TIMESTAMP
        """, (
            record_id, project_id, doi, normalized_title, title,
            authors_json, year, venue, doc_type, abstract,
            keywords_json, url, sources_json, raw_bibtex_key,
            duplicate_count, is_enriched_by_doi, prisma_stage
        ))
        conn.commit()
        return record_id


def get_corpus_papers(
    project_id: str = "default_slr",
    limit: int = 500,
    offset: int = 0,
    prisma_stage: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieves canonical papers for a given project."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if prisma_stage:
            cursor.execute("""
            SELECT * FROM corpus_papers
            WHERE project_id = ? AND prisma_stage = ?
            ORDER BY year DESC, title ASC LIMIT ? OFFSET ?
            """, (project_id, prisma_stage, limit, offset))
        else:
            cursor.execute("""
            SELECT * FROM corpus_papers
            WHERE project_id = ?
            ORDER BY year DESC, title ASC LIMIT ? OFFSET ?
            """, (project_id, limit, offset))
        
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["authors"] = json.loads(d.get("authors_json") or "[]")
            d["keywords"] = json.loads(d.get("keywords_json") or "[]")
            d["sources"] = json.loads(d.get("sources_json") or "[]")
            results.append(d)
        return results


def get_corpus_paper(record_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single canonical paper by record_id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM corpus_papers WHERE record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["authors"] = json.loads(d.get("authors_json") or "[]")
        d["keywords"] = json.loads(d.get("keywords_json") or "[]")
        d["sources"] = json.loads(d.get("sources_json") or "[]")
        return d


def get_corpus_summary(project_id: str = "default_slr") -> Dict[str, Any]:
    """Generates analytical summary of the corpus for dashboard/desktop."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 
            COUNT(*) as total_papers,
            SUM(duplicate_count) as total_raw_records,
            SUM(CASE WHEN is_enriched_by_doi = 1 THEN 1 ELSE 0 END) as enriched_count,
            SUM(CASE WHEN abstract != '' AND length(abstract) > 40 THEN 1 ELSE 0 END) as with_abstract_count,
            SUM(CASE WHEN doi IS NOT NULL AND doi != '' THEN 1 ELSE 0 END) as with_doi_count
        FROM corpus_papers
        WHERE project_id = ?
        """, (project_id,))
        summary = dict(cursor.fetchone() or {})
        
        # Count by source
        cursor.execute("SELECT sources_json FROM corpus_papers WHERE project_id = ?", (project_id,))
        rows = cursor.fetchall()
        sources_breakdown: Dict[str, int] = {}
        for r in rows:
            sources = json.loads(r["sources_json"] or "[]")
            for s in sources:
                sources_breakdown[s] = sources_breakdown.get(s, 0) + 1
        
        summary["sources_breakdown"] = sources_breakdown
        return summary


def delete_corpus_paper(record_id: str) -> bool:
    """Deletes a paper from the corpus."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM corpus_papers WHERE record_id = ?", (record_id,))
        conn.commit()
        return cursor.rowcount > 0


# --- Ingestion Jobs CRUD ---

def create_ingestion_job(
    job_id: str,
    database_name: str,
    query: str,
    total_expected: int = 0,
    project_id: str = "default_slr"
) -> str:
    """Initializes a new ingestion job tracker."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO ingestion_jobs (
            job_id, project_id, database_name, query, status,
            total_expected, fetched_count, enriched_count, deduplicated_count
        ) VALUES (?, ?, ?, ?, 'RUNNING', ?, 0, 0, 0)
        """, (job_id, project_id, database_name.lower(), query, total_expected))
        conn.commit()
        return job_id


def update_job_progress(
    job_id: str,
    fetched_count: Optional[int] = None,
    enriched_count: Optional[int] = None,
    deduplicated_count: Optional[int] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None
) -> None:
    """Updates counts and status of an ingestion job."""
    with get_connection() as conn:
        cursor = conn.cursor()
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params = []
        if fetched_count is not None:
            updates.append("fetched_count = ?")
            params.append(fetched_count)
        if enriched_count is not None:
            updates.append("enriched_count = ?")
            params.append(enriched_count)
        if deduplicated_count is not None:
            updates.append("deduplicated_count = ?")
            params.append(deduplicated_count)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        
        params.append(job_id)
        query_sql = f"UPDATE ingestion_jobs SET {', '.join(updates)} WHERE job_id = ?"
        cursor.execute(query_sql, params)
        conn.commit()


def get_ingestion_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves status and metrics of a specific ingestion job."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_ingestion_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieves list of latest ingestion jobs."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ingestion_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]

