use rusqlite::Connection;
use std::path::PathBuf;

fn open_db_conn() -> Result<Connection, rusqlite::Error> {
    let db_path = PathBuf::from("/home/glender/Proyectos/MCPCONECCT/data/mcpconecct.db");
    let conn = Connection::open(&db_path)?;
    conn.execute_batch("PRAGMA busy_timeout = 5000; PRAGMA journal_mode = WAL;")?;
    Ok(conn)
}

#[derive(Debug, Clone)]
pub struct SearchRecord {
    pub id: i64,
    pub timestamp: String,
    pub agent_name: String,
    pub database: String,
    pub search_mode: String,
    pub query: String,
    pub total_hits: i64,
    pub execution_time_ms: i64,
    pub status: String,
    pub bibtex_file: Option<String>,
    pub csv_file: Option<String>,
}

pub fn get_recent_history(limit: usize) -> Vec<SearchRecord> {
    let conn = match open_db_conn() {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let mut stmt = match conn.prepare(
        "SELECT id, timestamp, agent_name, database, search_mode, query, total_hits, execution_time_ms, status, bibtex_file, csv_file FROM search_history ORDER BY id DESC LIMIT ?"
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    let rows = stmt.query_map([limit], |row| {
        Ok(SearchRecord {
            id: row.get(0)?,
            timestamp: row.get(1)?,
            agent_name: row.get(2)?,
            database: row.get(3)?,
            search_mode: row.get(4)?,
            query: row.get(5)?,
            total_hits: row.get(6)?,
            execution_time_ms: row.get(7)?,
            status: row.get(8)?,
            bibtex_file: row.get(9)?,
            csv_file: row.get(10)?,
        })
    });

    match rows {
        Ok(iter) => iter.flatten().collect(),
        Err(_) => Vec::new(),
    }
}

#[derive(Debug, Clone)]
pub struct ExportRecord {
    pub id: i64,
    pub timestamp: String,
    pub filename: String,
    pub format: String,
    pub database: String,
    pub record_count: i64,
    pub file_path: String,
}

pub fn get_recent_exports(limit: usize) -> Vec<ExportRecord> {
    let conn = match open_db_conn() {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let mut stmt = match conn.prepare(
        "SELECT id, timestamp, filename, format, database, record_count, file_path FROM exports_registry ORDER BY id DESC LIMIT ?"
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    let rows = stmt.query_map([limit], |row| {
        Ok(ExportRecord {
            id: row.get(0)?,
            timestamp: row.get(1)?,
            filename: row.get(2)?,
            format: row.get(3)?,
            database: row.get(4)?,
            record_count: row.get(5)?,
            file_path: row.get(6)?,
        })
    });

    match rows {
        Ok(iter) => iter.flatten().collect(),
        Err(_) => Vec::new(),
    }
}

#[derive(Debug, Clone, Default)]
pub struct CorpusSummary {
    pub total_papers: i64,
    pub total_raw_records: i64,
    pub enriched_count: i64,
    pub with_abstract_count: i64,
}

#[derive(Debug, Clone)]
pub struct CorpusPaperRow {
    pub record_id: String,
    pub doi: Option<String>,
    pub title: String,
    pub authors: String,
    pub year: Option<i64>,
    pub venue: Option<String>,
    pub doc_type: String,
    pub abstract_text: String,
    pub sources: String,
    pub duplicate_count: i64,
    pub is_enriched_by_doi: bool,
}

#[derive(Debug, Clone)]
pub struct IngestionJobRow {
    pub job_id: String,
    pub database_name: String,
    pub query: String,
    pub status: String,
    pub total_expected: i64,
    pub fetched_count: i64,
    pub enriched_count: i64,
    pub deduplicated_count: i64,
}

pub fn get_corpus_summary(project_id: &str) -> CorpusSummary {
    let conn = match open_db_conn() {
        Ok(c) => c,
        Err(_) => return CorpusSummary::default(),
    };

    let sql = "SELECT 
        COUNT(*),
        COALESCE(SUM(duplicate_count), 0),
        COALESCE(SUM(CASE WHEN is_enriched_by_doi = 1 THEN 1 ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN abstract != '' AND length(abstract) > 40 THEN 1 ELSE 0 END), 0)
    FROM corpus_papers WHERE project_id = ?";

    let mut stmt = match conn.prepare(sql) {
        Ok(s) => s,
        Err(_) => return CorpusSummary::default(),
    };

    stmt.query_row([project_id], |row| {
        Ok(CorpusSummary {
            total_papers: row.get(0)?,
            total_raw_records: row.get(1)?,
            enriched_count: row.get(2)?,
            with_abstract_count: row.get(3)?,
        })
    }).unwrap_or_default()
}

pub fn get_corpus_papers(project_id: &str, limit: usize) -> Vec<CorpusPaperRow> {
    let conn = match open_db_conn() {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let sql = "SELECT record_id, doi, title, authors_json, year, venue, doc_type, abstract, sources_json, duplicate_count, is_enriched_by_doi 
               FROM corpus_papers WHERE project_id = ? ORDER BY year DESC, title ASC LIMIT ?";

    let mut stmt = match conn.prepare(sql) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    let rows = stmt.query_map(rusqlite::params![project_id, limit], |row| {
        Ok(CorpusPaperRow {
            record_id: row.get(0)?,
            doi: row.get(1)?,
            title: row.get(2)?,
            authors: row.get(3)?,
            year: row.get(4)?,
            venue: row.get(5)?,
            doc_type: row.get(6)?,
            abstract_text: row.get(7)?,
            sources: row.get(8)?,
            duplicate_count: row.get(9)?,
            is_enriched_by_doi: row.get::<_, i64>(10)? == 1,
        })
    });

    match rows {
        Ok(iter) => iter.flatten().collect(),
        Err(_) => Vec::new(),
    }
}

pub fn get_latest_ingestion_jobs(limit: usize) -> Vec<IngestionJobRow> {
    let conn = match open_db_conn() {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let sql = "SELECT job_id, database_name, query, status, total_expected, fetched_count, enriched_count, deduplicated_count 
               FROM ingestion_jobs ORDER BY created_at DESC LIMIT ?";

    let mut stmt = match conn.prepare(sql) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    let rows = stmt.query_map([limit], |row| {
        Ok(IngestionJobRow {
            job_id: row.get(0)?,
            database_name: row.get(1)?,
            query: row.get(2)?,
            status: row.get(3)?,
            total_expected: row.get(4)?,
            fetched_count: row.get(5)?,
            enriched_count: row.get(6)?,
            deduplicated_count: row.get(7)?,
        })
    });

    match rows {
        Ok(iter) => iter.flatten().collect(),
        Err(_) => Vec::new(),
    }
}
