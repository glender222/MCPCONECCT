import sqlite3
import pytest
from pathlib import Path
import tempfile
import uuid

from core.migrations.runner import run_migrations, backup_database, ensure_migration_table, is_migration_applied


def test_migrations_fresh_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fresh.db"
        applied = run_migrations(db_path, create_backup=False)
        assert applied == 1

        # Check tables exist
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {r[0] for r in cur.fetchall()}
        required_tables = {
            "schema_migrations", "research_projects", "research_questions",
            "research_objectives", "publications", "project_publications",
            "collections", "collection_members", "tags", "publication_tags",
            "annotations", "acquisition_runs", "source_observations",
            "research_events", "mutation_receipts", "publication_aliases"
        }
        assert required_tables.issubset(tables)

        # Second run should apply 0
        applied_again = run_migrations(db_path, create_backup=False)
        assert applied_again == 0
        conn.close()


def test_migrations_legacy_data_migration():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_legacy.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Create legacy corpus_papers table
        cur.execute("""
        CREATE TABLE corpus_papers (
            record_id TEXT PRIMARY KEY,
            project_id TEXT,
            doi TEXT,
            normalized_title TEXT,
            title TEXT,
            authors_json TEXT,
            year INTEGER,
            venue TEXT,
            doc_type TEXT,
            abstract TEXT,
            keywords_json TEXT,
            url TEXT,
            sources_json TEXT,
            raw_bibtex_key TEXT,
            duplicate_count INTEGER,
            is_enriched_by_doi BOOLEAN,
            prisma_stage TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """)

        # Insert legacy records
        cur.execute("""
        INSERT INTO corpus_papers (record_id, project_id, doi, normalized_title, title, authors_json, year, venue)
        VALUES ('rec1', 'slr_project_1', '10.1000/182', 'test paper title', 'Test Paper Title', '["Author One"]', 2023, 'Journal A');
        """)
        cur.execute("""
        INSERT INTO corpus_papers (record_id, project_id, doi, normalized_title, title, authors_json, year, venue)
        VALUES ('rec2', 'slr_project_1', '10.1000/182', 'test paper title duplicate', 'Test Paper Title Duplicate', '["Author One"]', 2023, 'Journal A');
        """)
        cur.execute("""
        INSERT INTO corpus_papers (record_id, project_id, doi, normalized_title, title, authors_json, year, venue)
        VALUES ('rec3', 'default_slr', NULL, 'another paper without doi', 'Another Paper Without DOI', '["Author Two"]', 2024, 'Conference B');
        """)
        conn.commit()
        conn.close()

        # Run migration
        applied = run_migrations(db_path, create_backup=True)
        assert applied == 1

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Verify projects created
        cur.execute("SELECT project_id, name FROM research_projects ORDER BY project_id")
        projects = {r[0]: r[1] for r in cur.fetchall()}
        assert "slr_project_1" in projects
        assert "default_slr" in projects

        # Verify publication reuse by DOI: rec1 and rec2 have same DOI so only 1 publication created for that DOI!
        cur.execute("SELECT COUNT(*) FROM publications WHERE doi = '10.1000/182'")
        assert cur.fetchone()[0] == 1

        # Total publications: 1 with DOI + 1 without DOI = 2 publications
        cur.execute("SELECT COUNT(*) FROM publications")
        assert cur.fetchone()[0] == 2

        # Aliases: 3 legacy records -> 3 aliases
        cur.execute("SELECT COUNT(*) FROM publication_aliases WHERE alias_type = 'LEGACY'")
        assert cur.fetchone()[0] == 3

        # Project memberships
        cur.execute("SELECT COUNT(*) FROM project_publications")
        assert cur.fetchone()[0] >= 2

        # Backup file was created
        backups = list((Path(tmpdir) / "backups").glob("*.db"))
        assert len(backups) == 1

        # Verify backup is restorable and valid
        backup_conn = sqlite3.connect(backups[0])
        b_cur = backup_conn.cursor()
        b_cur.execute("SELECT COUNT(*) FROM corpus_papers")
        assert b_cur.fetchone()[0] == 3
        backup_conn.close()

        conn.close()
