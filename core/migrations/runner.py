"""
Database Migration Engine for MCPCONECCT.
Handles atomic, repeatable schema migrations with online SQLite backup.
"""
from typing import Callable, List, Tuple
import sqlite3
import uuid
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger("mcpconecct.migrations")


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format with 'Z' suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def backup_database(src_conn: sqlite3.Connection, backup_path: Path) -> Path:
    """
    Creates a consistent, online backup of the SQLite database using SQLite's backup API.
    Safe with WAL mode.
    """
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    dst_conn = sqlite3.connect(backup_path)
    try:
        src_conn.backup(dst_conn)
        logger.info(f"Consistent database backup created at {backup_path}")
    finally:
        dst_conn.close()
    return backup_path


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    """)
    conn.commit()


def is_migration_applied(conn: sqlite3.Connection, version: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,))
    return cur.fetchone() is not None


def record_migration_applied(conn: sqlite3.Connection, version: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, utc_now_iso())
    )


# --- Migration 001: Block 2 Schema & Legacy Data Migration ---

def migration_001_block2_schema(conn: sqlite3.Connection) -> None:
    """
    Creates the 16 core tables for Block 2 and safely migrates legacy Block 1 data.
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. research_projects
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS research_projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        research_type TEXT NOT NULL DEFAULT '',
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1
    );
    """)

    # 2. research_questions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS research_questions (
        question_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 1
    );
    """)

    # 3. research_objectives
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS research_objectives (
        objective_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 1
    );
    """)

    # 4. publications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS publications (
        publication_id TEXT PRIMARY KEY,
        doi TEXT UNIQUE,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        authors_json TEXT NOT NULL DEFAULT '[]',
        year INTEGER,
        venue TEXT,
        doc_type TEXT NOT NULL DEFAULT 'other',
        abstract TEXT NOT NULL DEFAULT '',
        keywords_json TEXT NOT NULL DEFAULT '[]',
        url TEXT NOT NULL DEFAULT '',
        raw_bibtex_key TEXT NOT NULL DEFAULT '',
        citation_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pub_doi ON publications(doi);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pub_norm_title ON publications(normalized_title);")

    # 5. project_publications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_publications (
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        publication_id TEXT NOT NULL REFERENCES publications(publication_id) ON DELETE CASCADE,
        reading_status TEXT NOT NULL DEFAULT 'UNREAD' CHECK (reading_status IN ('UNREAD', 'READING', 'READ')),
        added_at TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (project_id, publication_id)
    );
    """)

    # 6. collections
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS collections (
        collection_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        UNIQUE (project_id, name_key)
    );
    """)

    # 7. collection_members
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS collection_members (
        collection_id TEXT NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL,
        publication_id TEXT NOT NULL,
        PRIMARY KEY (collection_id, publication_id),
        FOREIGN KEY (project_id, publication_id) REFERENCES project_publications(project_id, publication_id) ON DELETE CASCADE
    );
    """)

    # 8. tags
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        tag_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        UNIQUE (project_id, name_key)
    );
    """)

    # 9. publication_tags
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS publication_tags (
        tag_id TEXT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL,
        publication_id TEXT NOT NULL,
        PRIMARY KEY (tag_id, publication_id),
        FOREIGN KEY (project_id, publication_id) REFERENCES project_publications(project_id, publication_id) ON DELETE CASCADE
    );
    """)

    # 10. annotations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS annotations (
        annotation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        publication_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('NOTE', 'QUOTE', 'PARAPHRASE')),
        body TEXT NOT NULL,
        source_kind TEXT NOT NULL CHECK (source_kind IN ('NONE', 'ABSTRACT', 'FULLTEXT')),
        source_url TEXT,
        locator TEXT,
        question_id TEXT REFERENCES research_questions(question_id) ON DELETE SET NULL,
        actor_type TEXT NOT NULL DEFAULT 'HUMAN' CHECK (actor_type IN ('HUMAN', 'AGENT')),
        actor_label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (project_id, publication_id) REFERENCES project_publications(project_id, publication_id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_annot_project ON annotations(project_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_annot_pub ON annotations(publication_id);")

    # 11. acquisition_runs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS acquisition_runs (
        run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('SEARCH', 'IMPORT')),
        status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED')),
        request_json TEXT NOT NULL DEFAULT '{}',
        started_at TEXT NOT NULL,
        finished_at TEXT,
        reported_total INTEGER,
        observed_count INTEGER NOT NULL DEFAULT 0,
        unique_count INTEGER NOT NULL DEFAULT 0,
        stop_reason TEXT
    );
    """)

    # 12. source_observations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS source_observations (
        observation_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES acquisition_runs(run_id) ON DELETE CASCADE,
        publication_id TEXT NOT NULL REFERENCES publications(publication_id) ON DELETE CASCADE,
        source_record_key TEXT NOT NULL,
        raw_json TEXT NOT NULL DEFAULT '{}',
        received_at TEXT NOT NULL,
        UNIQUE (run_id, source_record_key)
    );
    """)

    # 13. research_events
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS research_events (
        event_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES research_projects(project_id) ON DELETE CASCADE,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        actor_type TEXT NOT NULL DEFAULT 'HUMAN',
        actor_label TEXT NOT NULL DEFAULT '',
        before_json TEXT,
        after_json TEXT,
        created_at TEXT NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_project ON research_events(project_id);")

    # 14. mutation_receipts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mutation_receipts (
        project_scope TEXT NOT NULL,
        operation TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        response_json TEXT NOT NULL,
        PRIMARY KEY (project_scope, operation, idempotency_key)
    );
    """)

    # 15. publication_aliases
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS publication_aliases (
        old_id TEXT PRIMARY KEY,
        publication_id TEXT NOT NULL REFERENCES publications(publication_id) ON DELETE CASCADE,
        alias_type TEXT NOT NULL CHECK (alias_type IN ('LEGACY', 'MERGED'))
    );
    """)

    # --- Legacy Data Migration ---
    # Check if corpus_papers exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='corpus_papers';")
    if cursor.fetchone():
        # 1. Distinct legacy project_ids
        cursor.execute("SELECT DISTINCT project_id FROM corpus_papers WHERE project_id IS NOT NULL AND project_id != '';")
        legacy_project_ids = [r[0] for r in cursor.fetchall()]
        if not legacy_project_ids:
            legacy_project_ids = ["default_slr"]
        elif "default_slr" not in legacy_project_ids:
            legacy_project_ids.append("default_slr")

        now_iso = utc_now_iso()
        for pid in legacy_project_ids:
            cursor.execute("SELECT 1 FROM research_projects WHERE project_id = ?", (pid,))
            if not cursor.fetchone():
                display_name = "Default Systematic Review" if pid == "default_slr" else f"Project {pid}"
                cursor.execute("""
                INSERT INTO research_projects (project_id, name, description, research_type, archived, created_at, updated_at, revision)
                VALUES (?, ?, ?, ?, 0, ?, ?, 1)
                """, (pid, display_name, "Migrated from legacy Block 1 corpus", "Systematic Literature Review", now_iso, now_iso))

        # 2. Migrate publications from corpus_papers
        cursor.execute("""
        SELECT record_id, project_id, doi, normalized_title, title, authors_json, year, venue, doc_type, abstract, keywords_json, url, raw_bibtex_key, created_at
        FROM corpus_papers
        """)
        legacy_papers = cursor.fetchall()
        for row in legacy_papers:
            rec_id = row[0]
            pid = row[1] or "default_slr"
            doi = row[2]
            if doi and not doi.strip():
                doi = None
            if doi:
                doi = doi.strip().lower()
            norm_title = row[3] or ""
            title = row[4] or ""
            authors_json = row[5] or "[]"
            year = row[6]
            venue = row[7]
            doc_type = row[8] or "other"
            abstract = row[9] or ""
            keywords_json = row[10] or "[]"
            url = row[11] or ""
            raw_bibtex_key = row[12] or ""
            row_created = row[13] or now_iso

            # Check if this record_id already has an alias
            cursor.execute("SELECT publication_id FROM publication_aliases WHERE old_id = ?", (rec_id,))
            alias_row = cursor.fetchone()
            if alias_row:
                pub_id = alias_row[0]
            else:
                # Check if publication exists by DOI
                pub_id = None
                if doi:
                    cursor.execute("SELECT publication_id FROM publications WHERE doi = ?", (doi,))
                    found = cursor.fetchone()
                    if found:
                        pub_id = found[0]

                if not pub_id:
                    pub_id = str(uuid.uuid4())
                    cursor.execute("""
                    INSERT INTO publications (
                        publication_id, doi, title, normalized_title, authors_json, year, venue,
                        doc_type, abstract, keywords_json, url, raw_bibtex_key, created_at, updated_at, revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """, (
                        pub_id, doi, title, norm_title, authors_json, year, venue,
                        doc_type, abstract, keywords_json, url, raw_bibtex_key, row_created, row_created
                    ))

                # Create alias
                cursor.execute("""
                INSERT OR IGNORE INTO publication_aliases (old_id, publication_id, alias_type)
                VALUES (?, ?, 'LEGACY')
                """, (rec_id, pub_id))

            # Ensure membership in project_publications
            cursor.execute("""
            INSERT OR IGNORE INTO project_publications (project_id, publication_id, reading_status, added_at, revision)
            VALUES (?, ?, 'UNREAD', ?, 1)
            """, (pid, pub_id, row_created))


MIGRATIONS: List[Tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("001_block2_schema", migration_001_block2_schema),
]


def run_migrations(db_path: Path = None, create_backup: bool = True) -> int:
    """
    Applies all pending migrations within a transaction.
    Returns count of applied migrations.
    """
    if db_path is None:
        db_path = settings.BASE_DIR / "data" / "mcpconecct.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        ensure_migration_table(conn)

        # Find pending migrations
        pending = []
        for version, func in MIGRATIONS:
            if not is_migration_applied(conn, version):
                pending.append((version, func))

        if not pending:
            return 0

        # Backup before applying migrations if requested
        if create_backup and db_path.exists() and db_path.stat().st_size > 0:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_file = db_path.parent / "backups" / f"backup_pre_migration_{timestamp}.db"
            backup_database(conn, backup_file)

        applied_count = 0
        for version, migration_func in pending:
            logger.info(f"Applying migration: {version}")
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE TRANSACTION;")
            try:
                migration_func(conn)
                record_migration_applied(conn, version)
                conn.commit()
                applied_count += 1
                logger.info(f"Migration {version} applied successfully.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Migration {version} failed: {e}. Rolled back.")
                raise e

        return applied_count
    finally:
        conn.close()
