use rusqlite::Connection;
use std::path::PathBuf;

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
    let db_path = PathBuf::from("/home/glender/Proyectos/MCPCONECCT/data/mcpconecct.db");
    if !db_path.exists() {
        return Vec::new();
    }

    let conn = match Connection::open(&db_path) {
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
    let db_path = PathBuf::from("/home/glender/Proyectos/MCPCONECCT/data/mcpconecct.db");
    if !db_path.exists() {
        return Vec::new();
    }

    let conn = match Connection::open(&db_path) {
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

