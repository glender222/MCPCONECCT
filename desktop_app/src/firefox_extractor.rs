use std::fs;
use std::path::{Path, PathBuf};
use rusqlite::Connection;
use serde_json::Value;

pub struct ExtractionResult {
    pub scopus_count: usize,
    pub ieee_count: usize,
    pub springer_count: usize,
    pub message: String,
}

pub fn find_firefox_profile() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let ff_dir = Path::new(&home).join(".mozilla/firefox");
    if !ff_dir.exists() {
        return None;
    }

    if let Ok(entries) = fs::read_dir(&ff_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() && (path.to_string_lossy().contains(".default") || path.to_string_lossy().contains("-esr")) {
                let cookies_file = path.join("cookies.sqlite");
                if cookies_file.exists() {
                    return Some(path);
                }
            }
        }
    }
    None
}

pub fn extract_cookies_from_firefox() -> Result<ExtractionResult, String> {
    let profile_path = find_firefox_profile()
        .ok_or_else(|| "No se encontró ningún perfil de Firefox en ~/.mozilla/firefox/".to_string())?;

    let cookies_sqlite = profile_path.join("cookies.sqlite");
    let cookies_wal = profile_path.join("cookies.sqlite-wal");
    let cookies_shm = profile_path.join("cookies.sqlite-shm");

    let temp_dir = PathBuf::from("/tmp/mcpconecct_ff_sync");
    let _ = fs::create_dir_all(&temp_dir);

    let temp_db = temp_dir.join("cookies.sqlite");
    let temp_wal = temp_dir.join("cookies.sqlite-wal");
    let temp_shm = temp_dir.join("cookies.sqlite-shm");

    // Copy to temporary files to avoid locking
    fs::copy(&cookies_sqlite, &temp_db)
        .map_err(|e| format!("Error al copiar cookies.sqlite: {}", e))?;
    if cookies_wal.exists() {
        let _ = fs::copy(&cookies_wal, &temp_wal);
    }
    if cookies_shm.exists() {
        let _ = fs::copy(&cookies_shm, &temp_shm);
    }

    let conn = Connection::open(&temp_db)
        .map_err(|e| format!("Error al abrir base de datos SQLite: {}", e))?;

    // Auto-detect ezproxy or openathens domains in cookies
    let mut detected_proxy_host: Option<String> = None;
    if let Ok(mut stmt) = conn.prepare("SELECT host FROM moz_cookies WHERE host LIKE '%ezproxy%' OR host LIKE '%openathens%' LIMIT 1") {
        if let Ok(mut rows) = stmt.query([]) {
            if let Ok(Some(row)) = rows.next() {
                if let Ok(h) = row.get::<_, String>(0) {
                    detected_proxy_host = Some(h.trim_start_matches('.').to_string());
                }
            }
        }
    }

    let query_cookies = |domain_kw: &str| -> Result<serde_json::Map<String, Value>, String> {

        let mut map = serde_json::Map::new();
        let sql = format!("SELECT name, value FROM moz_cookies WHERE host LIKE '%{}%'", domain_kw);
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        }).map_err(|e| e.to_string())?;

        for r in rows.flatten() {
            map.insert(r.0, Value::String(r.1));
        }
        Ok(map)
    };

    let mut scopus_map = query_cookies("scopus")?;
    let elsevier_map = query_cookies("elsevier")?;
    for (k, v) in elsevier_map {
        scopus_map.insert(k, v);
    }

    let mut ieee_map = query_cookies("ieeexplore")?;
    let ieee_org_map = query_cookies("ieee.org")?;
    for (k, v) in ieee_org_map {
        ieee_map.insert(k, v);
    }

    let mut springer_map = query_cookies("springer")?;
    let sn_map = query_cookies("springernature")?;
    for (k, v) in sn_map {
        springer_map.insert(k, v);
    }

    let scopus_count = scopus_map.len();
    let ieee_count = ieee_map.len();
    let springer_count = springer_map.len();

    // Update config/auth_store.json
    let auth_store_path = PathBuf::from("/home/glender/Proyectos/MCPCONECCT/config/auth_store.json");
    if auth_store_path.exists() {
        if let Ok(content) = fs::read_to_string(&auth_store_path) {
            if let Ok(mut json_val) = serde_json::from_str::<Value>(&content) {
                if let Some(obj) = json_val.as_object_mut() {
                    if let Some(sc) = obj.get_mut("scopus").and_then(|v| v.as_object_mut()) {
                        sc.insert("cookies".to_string(), Value::Object(scopus_map));
                        sc.insert("status".to_string(), Value::String("configured".to_string()));
                    }
                    if let Some(ie) = obj.get_mut("ieee").and_then(|v| v.as_object_mut()) {
                        ie.insert("cookies".to_string(), Value::Object(ieee_map));
                        ie.insert("status".to_string(), Value::String("configured".to_string()));
                    }
                    if let Some(sp) = obj.get_mut("springer").and_then(|v| v.as_object_mut()) {
                        sp.insert("cookies".to_string(), Value::Object(springer_map));
                        sp.insert("status".to_string(), Value::String("configured".to_string()));
                    }
                    if let Some(wos) = obj.get_mut("wos").and_then(|v| v.as_object_mut()) {
                        wos.insert("status".to_string(), Value::String("no_access".to_string()));
                    }

                    if let Some(ref proxy_host) = detected_proxy_host {
                        let full_proxy_url = format!("https://{}", proxy_host);
                        if let Some(ie) = obj.get_mut("ieee").and_then(|v| v.as_object_mut()) {
                            let curr = ie.get("base_url_override").and_then(|v| v.as_str()).unwrap_or("");
                            if curr.is_empty() && proxy_host.contains("ieee") {
                                ie.insert("base_url_override".to_string(), Value::String(full_proxy_url.clone()));
                            }
                        }
                    }
                }
                let _ = fs::write(&auth_store_path, serde_json::to_string_pretty(&json_val).unwrap_or_default());
            }
        }
    }

    Ok(ExtractionResult {
        scopus_count,
        ieee_count,
        springer_count,
        message: format!("Extraídas con éxito de Firefox: Scopus ({}), IEEE ({}), Springer ({})", scopus_count, ieee_count, springer_count),
    })
}
