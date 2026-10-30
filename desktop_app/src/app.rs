use std::sync::mpsc::{channel, Receiver, Sender};
use eframe::egui;
use serde::Deserialize;
use crate::burp_launcher::{is_burp_proxy_running, launch_browser_for_platform};
use crate::firefox_extractor::extract_cookies_from_firefox;
use crate::pico_translator::{translate_pico_query, TranslationResult};
use crate::db_client::{get_recent_history, get_recent_exports, SearchRecord, ExportRecord};

#[derive(PartialEq, Clone, Copy, Debug)]
pub enum ActiveTab {
    Connections,
    Calibration,
    Search,
    ExportsViewer,
    AgentAudit,
}

#[derive(PartialEq, Clone, Copy, Debug)]
pub enum AppTheme {
    DarkModern,
    AcademicLight,
}

fn de_string_lenient<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let opt = Option::<serde_json::Value>::deserialize(deserializer)?;
    match opt {
        Some(serde_json::Value::String(s)) => Ok(s),
        Some(serde_json::Value::Number(n)) => Ok(n.to_string()),
        Some(serde_json::Value::Bool(b)) => Ok(b.to_string()),
        _ => Ok(String::new()),
    }
}

fn de_vec_string_lenient<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let opt = Option::<serde_json::Value>::deserialize(deserializer)?;
    match opt {
        Some(serde_json::Value::Array(arr)) => {
            let mut list = Vec::new();
            for item in arr {
                match item {
                    serde_json::Value::String(s) => list.push(s),
                    serde_json::Value::Number(n) => list.push(n.to_string()),
                    _ => {}
                }
            }
            Ok(list)
        }
        _ => Ok(Vec::new()),
    }
}

#[derive(Clone, Debug, Default, serde::Deserialize, serde::Serialize)]
pub struct PaperItem {
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub title: String,
    #[serde(default, deserialize_with = "de_vec_string_lenient")]
    pub authors: Vec<String>,
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub year: String,
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub doi: String,
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub venue: String,
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub doc_type: String,
    #[serde(alias = "abstract", default, deserialize_with = "de_string_lenient")]
    pub abstract_text: String,
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub url: String,
    #[serde(default, deserialize_with = "de_string_lenient")]
    pub database: String,
}

#[derive(Clone, Debug)]
pub struct ToastMessage {
    pub text: String,
    pub is_error: bool,
    pub created_at: std::time::Instant,
}

pub enum AppEvent {
    SearchFinished {
        db: String,
        total: i64,
        papers: Vec<PaperItem>,
        error: Option<String>,
    },
    ExportFinished {
        format: String,
        filename: String,
        record_count: i64,
        preview_content: Option<String>,
        error: Option<String>,
    },
    ConnectionTestResult {
        db: String,
        connected: bool,
        message: String,
    },
    ExportsRefreshed(Vec<ExportRecord>),
    DiagnosticsFinished {
        results: std::collections::HashMap<String, String>,
    },
    CorpusIngestFinished {
        total_fetched: i64,
        total_enriched: i64,
        deduplicated_count: i64,
        error: Option<String>,
    },
    CorpusDeduplicateFinished {
        duplicates_removed: i64,
        final_count: i64,
        error: Option<String>,
    },
}

pub struct McpDesktopApp {
    pub event_tx: Sender<AppEvent>,
    pub event_rx: Receiver<AppEvent>,

    pub active_tab: ActiveTab,
    pub theme: AppTheme,
    pub status_message: String,
    pub burp_running: bool,

    // Loading / Async Indicators
    pub is_searching: bool,
    pub is_exporting: bool,
    pub loading_label: String,

    // PICO inputs
    pub pico_p: String,
    pub pico_i: String,
    pub pico_c: String,
    pub pico_o: String,
    pub translation: Option<TranslationResult>,

    // Search inputs
    pub selected_db: String,
    pub search_mode: String,
    pub search_query: String,
    pub year_start: i32,
    pub year_end: i32,

    // Database-specific Document Type Filters
    // IEEE
    pub ieee_periodicals: bool,
    pub ieee_conferences: bool,
    pub ieee_books: bool,
    pub ieee_standards: bool,
    pub ieee_early_access: bool,
    // Scopus
    pub scopus_articles: bool,
    pub scopus_conferences: bool,
    pub scopus_reviews: bool,
    pub scopus_books: bool,
    pub scopus_chapters: bool,
    // Springer
    pub springer_articles: bool,
    pub springer_conferences: bool,
    pub springer_chapters: bool,
    pub springer_books: bool,

    // Search Results
    pub total_results: i64,
    pub papers: Vec<PaperItem>,
    pub last_exported_bibtex: Option<String>,
    pub show_bibtex_drawer: bool,

    // Exports Viewer
    pub exports_list: Vec<ExportRecord>,
    pub selected_export: Option<ExportRecord>,
    pub selected_export_content: String,

    // History
    pub history: Vec<SearchRecord>,

    // Toasts & V2 Features
    pub toasts: std::collections::VecDeque<ToastMessage>,
    pub health_badges: std::collections::HashMap<String, String>,
    pub proxy_override_url: String,
    pub bulk_ingest_records: usize,
    pub enrich_missing_abstracts: bool,
    pub selected_citation_style: String,
    pub corpus_summary: crate::db_client::CorpusSummary,
    pub is_ingesting: bool,
    pub is_diagnosing: bool,
}

impl Default for McpDesktopApp {
    fn default() -> Self {
        let (tx, rx) = channel();
        let initial_exports = get_recent_exports(50);
        let first_export = initial_exports.first().cloned();
        let first_content = if let Some(exp) = &first_export {
            std::fs::read_to_string(&exp.file_path).unwrap_or_else(|_| "No se pudo leer el archivo.".to_string())
        } else {
            String::new()
        };

        let mut app = Self {
            event_tx: tx,
            event_rx: rx,
            active_tab: ActiveTab::Search,
            theme: AppTheme::DarkModern,
            status_message: "MCPCONECCT Desktop Hub listo. Selecciona una acción.".to_string(),
            burp_running: is_burp_proxy_running(),
            is_searching: false,
            is_exporting: false,
            loading_label: String::new(),

            toasts: std::collections::VecDeque::new(),
            health_badges: std::collections::HashMap::new(),
            proxy_override_url: String::new(),
            bulk_ingest_records: 50,
            enrich_missing_abstracts: true,
            selected_citation_style: "ieee".to_string(),
            corpus_summary: crate::db_client::get_corpus_summary("default_slr"),
            is_ingesting: false,
            is_diagnosing: false,

            pico_p: "\"unlearnable*\", \"availability poison*\", \"image cloaking\"".to_string(),
            pico_i: "\"countermeasure*\", \"defens*\", \"purif*\", \"adversarial training\"".to_string(),
            pico_c: "\"baseline*\", \"clean\", \"benchmark*\", \"original data\"".to_string(),
            pico_o: "\"accurac*\", \"performance*\", \"imperceptib*\", \"generaliz*\"".to_string(),
            translation: None,

            selected_db: "ieee".to_string(),
            search_mode: "advanced".to_string(),
            search_query: "(\"All Metadata\":\"unlearnable examples\")".to_string(),
            year_start: 2020,
            year_end: 2026,

            // Default filters
            ieee_periodicals: true,
            ieee_conferences: true,
            ieee_books: false,
            ieee_standards: false,
            ieee_early_access: false,

            scopus_articles: true,
            scopus_conferences: true,
            scopus_reviews: false,
            scopus_books: false,
            scopus_chapters: false,

            springer_articles: true,
            springer_conferences: true,
            springer_chapters: false,
            springer_books: false,

            total_results: 0,
            papers: Vec::new(),
            last_exported_bibtex: None,
            show_bibtex_drawer: false,

            exports_list: initial_exports,
            selected_export: first_export,
            selected_export_content: first_content,

            history: get_recent_history(50),
        };

        if std::env::var("MCPCONECCT_AUTO_SEARCH").is_ok() {
            app.trigger_async_search();
        }

        app
    }
}

impl McpDesktopApp {
    pub fn get_selected_doc_types(&self) -> Vec<String> {
        let mut types = Vec::new();
        match self.selected_db.as_str() {
            "ieee" => {
                if self.ieee_periodicals { types.push("periodicals".to_string()); }
                if self.ieee_conferences { types.push("conferences".to_string()); }
                if self.ieee_books { types.push("books".to_string()); }
                if self.ieee_standards { types.push("standards".to_string()); }
                if self.ieee_early_access { types.push("early access".to_string()); }
            }
            "scopus" => {
                if self.scopus_articles { types.push("ar".to_string()); }
                if self.scopus_conferences { types.push("cp".to_string()); }
                if self.scopus_reviews { types.push("re".to_string()); }
                if self.scopus_books { types.push("bk".to_string()); }
                if self.scopus_chapters { types.push("ch".to_string()); }
            }
            "springer" => {
                if self.springer_articles { types.push("Article".to_string()); }
                if self.springer_conferences { types.push("ConferencePaper".to_string()); }
                if self.springer_chapters { types.push("Chapter".to_string()); }
                if self.springer_books { types.push("Book".to_string()); }
            }
            _ => {}
        }
        types
    }

    fn apply_theme(&self, ctx: &egui::Context) {
        match self.theme {
            AppTheme::DarkModern => {
                ctx.set_visuals(egui::Visuals::dark());
            }
            AppTheme::AcademicLight => {
                ctx.set_visuals(egui::Visuals::light());
            }
        }
    }

    fn poll_async_events(&mut self) {
        while let Ok(event) = self.event_rx.try_recv() {
            match event {
                AppEvent::SearchFinished { db, total, papers, error } => {
                    self.is_searching = false;
                    if let Some(err) = error {
                        self.status_message = format!("❌ Error al buscar en {}: {}", db.to_uppercase(), err);
                    } else {
                        self.total_results = total;
                        self.status_message = format!("✅ Búsqueda exitosa en {}: {} resultados encontrados.", db.to_uppercase(), total);
                        self.papers = papers;
                        self.history = get_recent_history(50);
                    }
                }
                AppEvent::ExportFinished { format: _, filename, record_count, preview_content, error } => {
                    self.is_exporting = false;
                    if let Some(err) = error {
                        self.status_message = format!("❌ Error al exportar: {}", err);
                    } else {
                        self.status_message = format!("✅ Exportación exitosa: {} registros en exports/{}", record_count, filename);
                        if let Some(content) = preview_content {
                            self.last_exported_bibtex = Some(content);
                            self.show_bibtex_drawer = true;
                        }
                        self.exports_list = get_recent_exports(50);
                        if let Some(first) = self.exports_list.first() {
                            self.selected_export = Some(first.clone());
                            if let Ok(c) = std::fs::read_to_string(&first.file_path) {
                                self.selected_export_content = c;
                            }
                        }
                    }
                }
                AppEvent::ConnectionTestResult { db, connected, message } => {
                    if connected {
                        self.status_message = format!("✅ {}: {}", db.to_uppercase(), message);
                        self.add_toast(format!("Conexión exitosa con {}", db.to_uppercase()), false);
                    } else {
                        self.status_message = format!("❌ {}: {}", db.to_uppercase(), message);
                        self.add_toast(format!("Error en {}: {}", db.to_uppercase(), message), true);
                    }
                }
                AppEvent::DiagnosticsFinished { results } => {
                    self.is_diagnosing = false;
                    self.health_badges = results;
                    self.status_message = "Diagnóstico de salud de conexiones completado.".to_string();
                    self.add_toast("Diagnóstico de plataformas completado", false);
                }
                AppEvent::CorpusIngestFinished { total_fetched, total_enriched, deduplicated_count, error } => {
                    self.is_ingesting = false;
                    if let Some(err) = error {
                        self.status_message = format!("❌ Error en ingesta: {}", err);
                        self.add_toast(format!("Fallo en ingesta: {}", err), true);
                    } else {
                        self.corpus_summary = crate::db_client::get_corpus_summary("default_slr");
                        self.status_message = format!("✅ Ingesta finalizada: {} recuperados, {} enriquecidos DOI, {} únicos en corpus.", total_fetched, total_enriched, deduplicated_count);
                        self.add_toast(format!("Corpus actualizado: {} artículos listos", deduplicated_count), false);
                    }
                }
                AppEvent::CorpusDeduplicateFinished { duplicates_removed, final_count, error } => {
                    if let Some(err) = error {
                        self.status_message = format!("❌ Error en desduplicación: {}", err);
                        self.add_toast(format!("Error en desduplicación: {}", err), true);
                    } else {
                        self.corpus_summary = crate::db_client::get_corpus_summary("default_slr");
                        self.status_message = format!("✅ Desduplicación lista: {} duplicados fusionados (Total único: {}).", duplicates_removed, final_count);
                        self.add_toast(format!("Desduplicación: {} duplicados fusionados", duplicates_removed), false);
                    }
                }
                AppEvent::ExportsRefreshed(list) => {
                    self.exports_list = list;
                    if self.selected_export.is_none() {
                        if let Some(first) = self.exports_list.first() {
                            self.selected_export = Some(first.clone());
                            if let Ok(c) = std::fs::read_to_string(&first.file_path) {
                                self.selected_export_content = c;
                            }
                        }
                    }
                }
            }
        }
    }

    pub fn trigger_async_search(&mut self) {
        if self.is_searching {
            return;
        }

        let tx = self.event_tx.clone();
        let db = self.selected_db.clone();
        let query = self.search_query.clone();
        let mode = self.search_mode.clone();
        let y_start = self.year_start;
        let y_end = self.year_end;
        let doc_types = self.get_selected_doc_types();

        self.is_searching = true;
        self.loading_label = format!("Consultando {}...", db.to_uppercase());
        self.status_message = format!("Buscando en vivo en {}...", db.to_uppercase());

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default();

            let payload = serde_json::json!({
                "database": db,
                "query": query,
                "search_mode": mode,
                "year_start": y_start,
                "year_end": y_end,
                "doc_types": doc_types,
                "page_size": 25,
                "agent_name": "Rust Desktop App (Async)"
            });

            match client.post("http://127.0.0.1:8765/api/search").json(&payload).send() {
                Ok(resp) => {
                    let status = resp.status();
                    let body_text = resp.text().unwrap_or_default();
                    if status.is_success() {
                        if let Ok(data) = serde_json::from_str::<serde_json::Value>(&body_text) {
                            let total = data.get("total_results").and_then(|v| v.as_i64()).unwrap_or(0);
                            let mut papers = Vec::new();
                            if let Some(arr) = data.get("papers").and_then(|p| p.as_array()) {
                                for item in arr {
                                    match serde_json::from_value::<PaperItem>(item.clone()) {
                                        Ok(paper) => papers.push(paper),
                                        Err(e) => eprintln!("Error deserializando paper: {} en item: {:?}", e, item),
                                    }
                                }
                            }
                            let _ = tx.send(AppEvent::SearchFinished {
                                db,
                                total,
                                papers,
                                error: None,
                            });
                            return;
                        }
                    }
                    let _ = tx.send(AppEvent::SearchFinished {
                        db,
                        total: 0,
                        papers: Vec::new(),
                        error: Some(format!("HTTP {}: {}", status, body_text)),
                    });
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::SearchFinished {
                        db,
                        total: 0,
                        papers: Vec::new(),
                        error: Some(format!("Error de conexión: {}", e)),
                    });
                }
            }
        });
    }

    pub fn trigger_async_export(&mut self, format: &str) {
        if self.is_exporting {
            return;
        }

        let tx = self.event_tx.clone();
        let db = self.selected_db.clone();
        let query = self.search_query.clone();
        let y_start = self.year_start;
        let y_end = self.year_end;
        let fmt = format.to_string();

        self.is_exporting = true;
        self.loading_label = format!("Generando {}...", fmt.to_uppercase());
        self.status_message = format!("Exportando búsqueda a {}...", fmt.to_uppercase());

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default();

            let payload = serde_json::json!({
                "database": db,
                "query": query,
                "format": fmt,
                "year_start": y_start,
                "year_end": y_end,
                "max_records": 100,
                "agent_name": "Rust Desktop App (Async)"
            });

            match client.post("http://127.0.0.1:8765/api/export").json(&payload).send() {
                Ok(resp) => {
                    let status = resp.status();
                    let body_text = resp.text().unwrap_or_default();
                    if status.is_success() {
                        if let Ok(data) = serde_json::from_str::<serde_json::Value>(&body_text) {
                            let filename = data.get("filename").and_then(|v| v.as_str()).unwrap_or("export").to_string();
                            let record_count = data.get("records_exported").and_then(|v| v.as_i64()).unwrap_or(0);
                            let file_path = data.get("file_path").and_then(|v| v.as_str()).unwrap_or("").to_string();

                            let preview_content = if !file_path.is_empty() {
                                std::fs::read_to_string(&file_path).ok()
                            } else {
                                None
                            };

                            let _ = tx.send(AppEvent::ExportFinished {
                                format: fmt,
                                filename,
                                record_count,
                                preview_content,
                                error: None,
                            });
                            return;
                        }
                    }
                    let _ = tx.send(AppEvent::ExportFinished {
                        format: fmt,
                        filename: "".to_string(),
                        record_count: 0,
                        preview_content: None,
                        error: Some(format!("HTTP {}: {}", status, body_text)),
                    });
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::ExportFinished {
                        format: fmt,
                        filename: "".to_string(),
                        record_count: 0,
                        preview_content: None,
                        error: Some(format!("Error de conexión: {}", e)),
                    });
                }
            }
        });
    }

    pub fn trigger_async_test_connection(&mut self, db: &str) {
        let tx = self.event_tx.clone();
        let db_str = db.to_string();
        self.status_message = format!("Probando conexión con {}...", db_str.to_uppercase());

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(15))
                .build()
                .unwrap_or_default();

            let payload = serde_json::json!({ "database": db_str });
            match client.post("http://127.0.0.1:8765/api/connections/test").json(&payload).send() {
                Ok(resp) => {
                    if let Ok(data) = resp.json::<serde_json::Value>() {
                        let connected = data.get("connected").and_then(|v| v.as_bool()).unwrap_or(false);
                        let message = data.get("message").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let _ = tx.send(AppEvent::ConnectionTestResult {
                            db: db_str,
                            connected,
                            message,
                        });
                        return;
                    }
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::ConnectionTestResult {
                        db: db_str,
                        connected: false,
                        message: format!("Error de conexión: {}", e),
                    });
                }
            }
        });
    }

    pub fn add_toast(&mut self, text: impl Into<String>, is_error: bool) {
        self.toasts.push_back(ToastMessage {
            text: text.into(),
            is_error,
            created_at: std::time::Instant::now(),
        });
    }

    pub fn trigger_async_diagnostics(&mut self) {
        if self.is_diagnosing {
            return;
        }
        self.is_diagnosing = true;
        self.status_message = "Ejecutando diagnóstico de salud y WAF en plataformas...".to_string();
        let tx = self.event_tx.clone();

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(25))
                .build()
                .unwrap_or_default();

            let mut results = std::collections::HashMap::new();
            if let Ok(resp) = client.get("http://127.0.0.1:8765/api/connections/diagnose").send() {
                if let Ok(data) = resp.json::<serde_json::Value>() {
                    if let Some(diag) = data.get("diagnostics").and_then(|d| d.as_object()) {
                        for (k, v) in diag {
                            let status = v.get("status").and_then(|s| s.as_str()).unwrap_or("UNKNOWN").to_string();
                            results.insert(k.clone(), status);
                        }
                    }
                }
            }
            let _ = tx.send(AppEvent::DiagnosticsFinished { results });
        });
    }

    pub fn trigger_async_ingest(&mut self) {
        if self.is_ingesting {
            return;
        }
        self.is_ingesting = true;
        self.loading_label = "Streaming e Ingesta a Corpus Central...".to_string();
        self.status_message = format!("Iniciando ingesta de {} registros en {}...", self.bulk_ingest_records, self.selected_db.to_uppercase());
        let tx = self.event_tx.clone();
        let db = self.selected_db.clone();
        let query = self.search_query.clone();
        let max_records = self.bulk_ingest_records;
        let enrich = self.enrich_missing_abstracts;
        let y_start = self.year_start;
        let y_end = self.year_end;
        let doc_types = self.get_selected_doc_types();

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()
                .unwrap_or_default();

            let payload = serde_json::json!({
                "database": db,
                "query": query,
                "max_records": max_records,
                "project_id": "default_slr",
                "year_start": y_start,
                "year_end": y_end,
                "doc_types": doc_types,
                "enrich_missing_abstracts": enrich,
                "background": false
            });

            match client.post("http://127.0.0.1:8765/api/corpus/ingest").json(&payload).send() {
                Ok(resp) => {
                    if let Ok(data) = resp.json::<serde_json::Value>() {
                        let total_fetched = data.get("total_fetched").and_then(|v| v.as_i64()).unwrap_or(0);
                        let total_enriched = data.get("total_enriched").and_then(|v| v.as_i64()).unwrap_or(0);
                        let deduplicated_count = data.get("deduplicated_count").and_then(|v| v.as_i64()).unwrap_or(0);
                        let _ = tx.send(AppEvent::CorpusIngestFinished {
                            total_fetched,
                            total_enriched,
                            deduplicated_count,
                            error: None,
                        });
                        return;
                    }
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::CorpusIngestFinished {
                        total_fetched: 0,
                        total_enriched: 0,
                        deduplicated_count: 0,
                        error: Some(format!("Error: {}", e)),
                    });
                }
            }
        });
    }

    pub fn trigger_async_deduplicate(&mut self) {
        self.status_message = "Ejecutando desduplicación cross-database en 2 fases...".to_string();
        let tx = self.event_tx.clone();

        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default();

            let payload = serde_json::json!({
                "project_id": "default_slr",
                "fuzzy_threshold": 0.92
            });

            match client.post("http://127.0.0.1:8765/api/corpus/deduplicate").json(&payload).send() {
                Ok(resp) => {
                    if let Ok(data) = resp.json::<serde_json::Value>() {
                        let duplicates_removed = data.get("duplicates_removed").and_then(|v| v.as_i64()).unwrap_or(0);
                        let final_count = data.get("final_count").and_then(|v| v.as_i64()).unwrap_or(0);
                        let _ = tx.send(AppEvent::CorpusDeduplicateFinished {
                            duplicates_removed,
                            final_count,
                            error: None,
                        });
                        return;
                    }
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::CorpusDeduplicateFinished {
                        duplicates_removed: 0,
                        final_count: 0,
                        error: Some(format!("Error: {}", e)),
                    });
                }
            }
        });
    }

    pub fn format_citation_for_paper(paper: &PaperItem, style: &str) -> String {
        let title = paper.title.trim_end_matches(['.', ',']);
        let venue = &paper.venue;
        let year = &paper.year;
        let doi = &paper.doi;

        match style {
            "ieee" => {
                let author_str = if paper.authors.is_empty() {
                    "Anon.".to_string()
                } else if paper.authors.len() > 3 {
                    format!("{} et al.", paper.authors[0])
                } else {
                    paper.authors.join(", ")
                };
                if !doi.is_empty() {
                    format!("[1] {}, \"{},\" {}, {}, doi: {}.", author_str, title, venue, year, doi)
                } else {
                    format!("[1] {}, \"{},\" {}, {}.", author_str, title, venue, year)
                }
            }
            "apa7" => {
                let author_str = if paper.authors.is_empty() {
                    "Unknown".to_string()
                } else {
                    paper.authors.join(", ")
                };
                if !doi.is_empty() {
                    format!("{} ({}). {}. {}. https://doi.org/{}", author_str, year, title, venue, doi)
                } else {
                    format!("{} ({}). {}. {}.", author_str, year, title, venue)
                }
            }
            "bibitem" => {
                let first_author = paper.authors.first().map(|a| a.split_whitespace().last().unwrap_or("anon")).unwrap_or("anon").to_lowercase();
                let key = format!("{}{}", first_author, year);
                let author_str = paper.authors.join(", ");
                format!("\\bibitem{{{}}} {}, ``{},'' \\textit{{{}}}, {}.", key, author_str, title, venue, year)
            }
            _ => {
                format!("@article{{rec,\n  title = {{{}}},\n  year = {{{}}},\n  doi = {{{}}}\n}}", title, year, doi)
            }
        }
    }

    pub fn save_university_proxy(&mut self) {
        let auth_path = std::path::PathBuf::from("/home/glender/Proyectos/MCPCONECCT/config/auth_store.json");
        if let Ok(content) = std::fs::read_to_string(&auth_path) {
            if let Ok(mut json_val) = serde_json::from_str::<serde_json::Value>(&content) {
                if let Some(obj) = json_val.as_object_mut() {
                    if let Some(entry) = obj.get_mut(&self.selected_db).and_then(|v| v.as_object_mut()) {
                        entry.insert("base_url_override".to_string(), serde_json::Value::String(self.proxy_override_url.clone()));
                    }
                }
                let _ = std::fs::write(&auth_path, serde_json::to_string_pretty(&json_val).unwrap_or_default());
                self.add_toast(format!("Proxy configurado para {}", self.selected_db.to_uppercase()), false);
            }
        }
    }

    pub fn render_health_badge(&self, ui: &mut egui::Ui, db_name: &str) {
        let status = self.health_badges.get(db_name).map(|s| s.as_str()).unwrap_or("UNKNOWN");
        match status {
            "VALID_INSTITUTIONAL" => {
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "🟢 INSTITUCIONAL ACTIVO");
            }
            "VALID_PUBLIC" => {
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), "🔵 ACCESO PÚBLICO / OPEN ACCESS");
            }
            "WAF_CHALLENGE" => {
                ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "🔴 DESAFÍO WAF / BLOQUEO DETECTADO");
            }
            "SESSION_EXPIRED" => {
                ui.colored_label(egui::Color32::from_rgb(234, 179, 8), "🟡 SESIÓN EXPIRADA / LOGIN REQUERIDO");
            }
            _ => {
                ui.colored_label(egui::Color32::GRAY, "⚪ ESTADO NO VERIFICADO");
            }
        }
    }
}

impl eframe::App for McpDesktopApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        // Poll background events
        self.poll_async_events();

        // Apply theme
        self.apply_theme(ui.ctx());

        // Top Header Panel
        egui::Panel::top("top_panel").show(ui, |ui| {
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                ui.heading("🎓 MCPCONECCT · Academic Core Desktop");

                // Right side controls: Theme switch, Burp status, Loading Spinner
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    // Theme Switcher
                    let theme_btn_text = match self.theme {
                        AppTheme::DarkModern => "☀️ Modo Claro",
                        AppTheme::AcademicLight => "🌙 Modo Oscuro",
                    };
                    if ui.button(theme_btn_text).clicked() {
                        self.theme = match self.theme {
                            AppTheme::DarkModern => AppTheme::AcademicLight,
                            AppTheme::AcademicLight => AppTheme::DarkModern,
                        };
                    }

                    ui.separator();

                    if ui.button("🔄 Actualizar Burp").clicked() {
                        self.burp_running = is_burp_proxy_running();
                    }
                    if self.burp_running {
                        ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "🟢 Burp Suite: Activo (127.0.0.1:8080)");
                    } else {
                        ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "🔴 Burp Suite: Inactivo");
                    }

                    // Async activity indicator
                    if self.is_searching || self.is_exporting {
                        ui.separator();
                        ui.spinner();
                        ui.colored_label(egui::Color32::from_rgb(59, 130, 246), &self.loading_label);
                        ui.ctx().request_repaint();
                    }
                });
            });
            ui.add_space(6.0);
        });

        // Bottom Status Bar
        egui::Panel::bottom("bottom_panel").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label("Estado:");
                let status_color = if self.status_message.starts_with('✅') {
                    egui::Color32::from_rgb(34, 197, 94)
                } else if self.status_message.starts_with('❌') {
                    egui::Color32::from_rgb(239, 68, 68)
                } else {
                    egui::Color32::LIGHT_BLUE
                };
                ui.colored_label(status_color, &self.status_message);
            });
        });

        // Main Central Panel
        egui::CentralPanel::default().show(ui, |ui| {
            // Tab Selector Navigation
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.active_tab, ActiveTab::Connections, "⚡ Conexiones & 1-Clic Burp");
                ui.selectable_value(&mut self.active_tab, ActiveTab::Calibration, "🔬 Calibrador PICO & RSL");
                ui.selectable_value(&mut self.active_tab, ActiveTab::Search, "🔍 Búsqueda Avanzada Multi-Filtro");
                ui.selectable_value(&mut self.active_tab, ActiveTab::ExportsViewer, "📁 Visor de Exportaciones & BibTeX");
                ui.selectable_value(&mut self.active_tab, ActiveTab::AgentAudit, "🤖 Auditoría de Agentes");
            });
            ui.separator();

            match self.active_tab {
                ActiveTab::Connections => self.render_connections_tab(ui),
                ActiveTab::Calibration => self.render_calibration_tab(ui),
                ActiveTab::Search => self.render_search_tab(ui),
                ActiveTab::ExportsViewer => self.render_exports_viewer_tab(ui),
                ActiveTab::AgentAudit => self.render_audit_tab(ui),
            }
        });

        // Floating Toast Notification System (bottom right)
        self.toasts.retain(|t| t.created_at.elapsed().as_secs_f32() < 4.0);
        if !self.toasts.is_empty() {
            egui::Area::new(egui::Id::new("toasts_overlay_area"))
                .anchor(egui::Align2::RIGHT_BOTTOM, egui::vec2(-20.0, -35.0))
                .show(ui.ctx(), |ui| {
                    for toast in &self.toasts {
                        let (bg, border) = if toast.is_error {
                            (egui::Color32::from_rgb(60, 20, 20), egui::Color32::from_rgb(239, 68, 68))
                        } else {
                            (egui::Color32::from_rgb(20, 60, 30), egui::Color32::from_rgb(34, 197, 94))
                        };
                        egui::Frame::new()
                            .fill(bg)
                            .stroke(egui::Stroke::new(1.5, border))
                            .corner_radius(6.0)
                            .inner_margin(8.0)
                            .show(ui, |ui| {
                                ui.label(egui::RichText::new(&toast.text).color(egui::Color32::WHITE).strong());
                            });
                        ui.add_space(4.0);
                    }
                });
        }
    }
}

impl McpDesktopApp {
    fn render_connections_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Gestión Automatizada de Sesiones y Credenciales");
        ui.label("Captura de credenciales directa desde Firefox y navegación enrutada a través de Burp Suite.");
        ui.add_space(8.0);

        // Global Diagnostic & Health Check Bar
        ui.horizontal(|ui| {
            let diag_btn = ui.add_enabled(!self.is_diagnosing, egui::Button::new("🧪 Diagnosticar Salud de Conexiones & WAF"));
            if diag_btn.clicked() {
                self.trigger_async_diagnostics();
            }
            if self.is_diagnosing {
                ui.spinner();
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), "Sondeando conexiones...");
            }
        });
        ui.add_space(6.0);

        // One-Click Firefox Auto-Extractor
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.label("🦊 Auto-Captura Directa:");
                if ui.button("⚡ Extraer Automáticamente Sesiones desde Firefox (1-Clic)").clicked() {
                    match extract_cookies_from_firefox() {
                        Ok(res) => {
                            self.status_message = res.message.clone();
                            self.add_toast(res.message, false);
                        }
                        Err(err) => {
                            self.status_message = format!("Error: {}", err);
                            self.add_toast(format!("Error: {}", err), true);
                        }
                    }
                }
            });
            ui.label("Lee directamente cookies.sqlite de tu perfil de Firefox para Scopus, IEEE y SpringerLink sin bloquear la base.");
        });

        ui.add_space(10.0);
        ui.heading("Estado de Conexión & Enrutamiento Burp Suite (127.0.0.1:8080)");

        // 3 Active Platforms (and WoS disabled)
        ui.columns(3, |columns| {
            // Scopus
            columns[0].group(|ui| {
                ui.heading("Scopus (Elsevier)");
                self.render_health_badge(ui, "scopus");
                ui.label("Restricción: Comodines tras guión no expanden.");
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    if ui.button("🌐 Abrir en Burp").clicked() {
                        match launch_browser_for_platform("scopus") {
                            Ok(msg) => self.status_message = msg,
                            Err(e) => self.status_message = e,
                        }
                    }
                    if ui.button("🧪 Probar").clicked() {
                        self.trigger_async_test_connection("scopus");
                    }
                });
            });

            // IEEE Xplore
            columns[1].group(|ui| {
                ui.heading("IEEE Xplore");
                self.render_health_badge(ui, "ieee");
                ui.label("Restricción: Máximo 10 comodines (*).");
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    if ui.button("🌐 Abrir en Burp").clicked() {
                        match launch_browser_for_platform("ieee") {
                            Ok(msg) => self.status_message = msg,
                            Err(e) => self.status_message = e,
                        }
                    }
                    if ui.button("🧪 Probar").clicked() {
                        self.trigger_async_test_connection("ieee");
                    }
                });
            });

            // SpringerLink
            columns[2].group(|ui| {
                ui.heading("SpringerLink");
                self.render_health_badge(ui, "springer");
                ui.label("Búsqueda y metadatos públicos directos.");
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    if ui.button("🌐 Abrir en Burp").clicked() {
                        match launch_browser_for_platform("springer") {
                            Ok(msg) => self.status_message = msg,
                            Err(e) => self.status_message = e,
                        }
                    }
                    if ui.button("🧪 Probar").clicked() {
                        self.trigger_async_test_connection("springer");
                    }
                });
            });
        });

        ui.add_space(10.0);
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.label("Web of Science (WoS):");
                self.render_health_badge(ui, "wos");
            });
        });

        // University Proxy URL Override Box
        ui.add_space(10.0);
        ui.group(|ui| {
            ui.heading("🏛️ Soporte de Proxy Universitario (EZProxy / OpenAthens)");
            ui.label("Reescribe las peticiones para acceder con la suscripción de tu universidad (ej. https://ieeexplore-ieee-org.ezproxy.universidad.edu.pe).");
            ui.horizontal(|ui| {
                ui.label("Base a configurar:");
                ui.selectable_value(&mut self.selected_db, "ieee".to_string(), "IEEE");
                ui.selectable_value(&mut self.selected_db, "scopus".to_string(), "Scopus");
                ui.selectable_value(&mut self.selected_db, "springer".to_string(), "Springer");
                ui.selectable_value(&mut self.selected_db, "wos".to_string(), "WoS");
            });
            ui.horizontal(|ui| {
                ui.label("URL Base Proxy:");
                ui.text_edit_singleline(&mut self.proxy_override_url);
                if ui.button("💾 Guardar Proxy").clicked() {
                    self.save_university_proxy();
                }
            });
        });
    }

    fn render_calibration_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Estudio de Calibración PICO & Ecuaciones RSL");
        ui.horizontal(|ui| {
            if ui.button("🧪 Cargar Ecuación RSL de Perturbación Proactiva (ESM_1.tex)").clicked() {
                self.pico_p = "\"unlearnable*\", \"availability poison*\", \"perturbative availability\", \"error-minimizing noise\", \"indiscriminate poisoning\", \"image cloaking\", \"facial privacy protection\", \"unauthorized training\"".to_string();
                self.pico_i = "\"countermeasure*\", \"defens*\", \"defenc*\", \"defend*\", \"attack*\", \"break*\", \"bypass*\", \"adversarial training\", \"augment*\", \"purif*\", \"ensemble*\", \"fine-tuning\"".to_string();
                self.pico_c = "\"baseline*\", \"clean\", \"existing\", \"previous*\", \"benchmark*\", \"original data\"".to_string();
                self.pico_o = "\"accurac*\", \"performance*\", \"effective*\", \"success rate*\", \"imperceptib*\", \"generaliz*\"".to_string();
                self.translation = Some(translate_pico_query(&self.pico_p, &self.pico_i, &self.pico_c, &self.pico_o));
                self.status_message = "Ecuación de la RSL cargada y traducida.".to_string();
            }

            if ui.button("🔄 Traducir y Validar").clicked() {
                self.translation = Some(translate_pico_query(&self.pico_p, &self.pico_i, &self.pico_c, &self.pico_o));
                self.status_message = "Ecuación traducida para las 3 plataformas.".to_string();
            }
        });

        ui.add_space(8.0);
        ui.columns(2, |cols| {
            cols[0].group(|ui| {
                ui.label("[P] Población / Problema:");
                ui.text_edit_multiline(&mut self.pico_p);
                ui.add_space(4.0);
                ui.label("[I] Intervención / Técnica:");
                ui.text_edit_multiline(&mut self.pico_i);
            });
            cols[1].group(|ui| {
                ui.label("[C] Comparación / Baseline:");
                ui.text_edit_multiline(&mut self.pico_c);
                ui.add_space(4.0);
                ui.label("[O] Resultado / Métrica:");
                ui.text_edit_multiline(&mut self.pico_o);
            });
        });

        if let Some(trans) = &self.translation {
            ui.add_space(10.0);
            ui.group(|ui| {
                ui.heading("Traducción Sincronizada y Linters de Restricciones");

                // IEEE Linter Check
                if trans.ieee_valid {
                    ui.colored_label(egui::Color32::from_rgb(34, 197, 94), format!("✅ IEEE Xplore: {} / 10 comodines utilizados (VÁLIDO)", trans.ieee_wildcard_count));
                } else {
                    ui.colored_label(egui::Color32::from_rgb(239, 68, 68), format!("❌ IEEE Xplore: {} comodines detectados (SUPERA EL LÍMITE DE 10)", trans.ieee_wildcard_count));
                }

                // Scopus Warnings
                for w in &trans.scopus_warnings {
                    ui.colored_label(egui::Color32::GOLD, format!("⚠️ {}", w));
                }

                ui.add_space(6.0);
                ui.label("Ecuación IEEE Xplore:");
                ui.text_edit_multiline(&mut trans.ieee.clone());
                ui.add_space(4.0);
                ui.label("Ecuación Scopus:");
                ui.text_edit_multiline(&mut trans.scopus.clone());
                ui.add_space(4.0);
                ui.label("Ecuación SpringerLink:");
                ui.text_edit_multiline(&mut trans.springer.clone());
            });
        }
    }

    fn render_search_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Búsqueda Avanzada Multi-Filtro & Ingesta al Corpus Central");

        // Central Corpus Summary Banner
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.strong("🗄️ Corpus Central SLR (default_slr):");
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), format!("{} Artículos Únicos", self.corpus_summary.total_papers));
                ui.label("·");
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), format!("{} Enriquecidos DOI", self.corpus_summary.enriched_count));
                ui.label("·");
                ui.colored_label(egui::Color32::LIGHT_BLUE, format!("{} con Abstract", self.corpus_summary.with_abstract_count));
                if ui.button("🔄").clicked() {
                    self.corpus_summary = crate::db_client::get_corpus_summary("default_slr");
                }
            });
        });
        ui.add_space(4.0);

        ui.horizontal(|ui| {
            ui.label("Base de datos:");
            ui.selectable_value(&mut self.selected_db, "ieee".to_string(), "⚡ IEEE Xplore");
            ui.selectable_value(&mut self.selected_db, "springer".to_string(), "📚 SpringerLink (Sin Login)");
            ui.selectable_value(&mut self.selected_db, "scopus".to_string(), "🔬 Scopus (Elsevier)");
        });

        ui.horizontal(|ui| {
            ui.label("Modo:");
            ui.selectable_value(&mut self.search_mode, "advanced".to_string(), "Avanzada (Booleana)");
            ui.selectable_value(&mut self.search_mode, "normal".to_string(), "Normal (Palabras clave)");
            ui.separator();
            ui.label("Rango de Años:");
            ui.add(egui::DragValue::new(&mut self.year_start).range(1990..=2030));
            ui.label("a");
            ui.add(egui::DragValue::new(&mut self.year_end).range(1990..=2030));
        });

        // Dynamic Document Type Filters tailored to the selected database
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.strong("Filtros por Tipo de Documento:");
                match self.selected_db.as_str() {
                    "ieee" => {
                        ui.checkbox(&mut self.ieee_periodicals, "Revistas (Journals)");
                        ui.checkbox(&mut self.ieee_conferences, "Conferencias (Conferences)");
                        ui.checkbox(&mut self.ieee_books, "Libros (Books)");
                        ui.checkbox(&mut self.ieee_standards, "Normas (Standards)");
                        ui.checkbox(&mut self.ieee_early_access, "Early Access");
                    }
                    "scopus" => {
                        ui.checkbox(&mut self.scopus_articles, "Artículos (Articles)");
                        ui.checkbox(&mut self.scopus_conferences, "Conferencias (Conference Papers)");
                        ui.checkbox(&mut self.scopus_reviews, "Revisiones (Reviews)");
                        ui.checkbox(&mut self.scopus_books, "Libros (Books)");
                        ui.checkbox(&mut self.scopus_chapters, "Capítulos (Book Chapters)");
                    }
                    "springer" => {
                        ui.checkbox(&mut self.springer_articles, "Artículos (Articles)");
                        ui.checkbox(&mut self.springer_conferences, "Actas (Conference Papers)");
                        ui.checkbox(&mut self.springer_chapters, "Capítulos de Libros");
                        ui.checkbox(&mut self.springer_books, "Libros / Monografías");
                    }
                    _ => {}
                }
            });
        });

        ui.add_space(4.0);
        ui.label("Consulta de Búsqueda:");
        ui.text_edit_multiline(&mut self.search_query);

        ui.horizontal(|ui| {
            // Non-blocking search button
            let search_btn = ui.add_enabled(!self.is_searching, egui::Button::new("🔍 Búsqueda Rápida"));
            if search_btn.clicked() {
                self.trigger_async_search();
            }

            // Bulk Ingest controls
            ui.separator();
            ui.label("Lote:");
            ui.add(egui::DragValue::new(&mut self.bulk_ingest_records).range(10..=500));
            ui.checkbox(&mut self.enrich_missing_abstracts, "Enriquecer DOI");

            let ingest_btn = ui.add_enabled(!self.is_ingesting, egui::Button::new("📥 Ingestar Streaming"));
            if ingest_btn.clicked() {
                self.trigger_async_ingest();
            }

            let dedup_btn = ui.button("🔄 Desduplicar Corpus");
            if dedup_btn.clicked() {
                self.trigger_async_deduplicate();
            }

            // Export buttons
            ui.separator();
            let exp_bib_btn = ui.add_enabled(!self.is_exporting, egui::Button::new("📥 .BIB"));
            if exp_bib_btn.clicked() {
                self.trigger_async_export("bibtex");
            }

            let exp_csv_btn = ui.add_enabled(!self.is_exporting, egui::Button::new("📥 .CSV"));
            if exp_csv_btn.clicked() {
                self.trigger_async_export("csv");
            }

            let exp_ris_btn = ui.add_enabled(!self.is_exporting, egui::Button::new("📥 .RIS"));
            if exp_ris_btn.clicked() {
                self.trigger_async_export("ris");
            }

            if self.is_searching || self.is_exporting || self.is_ingesting {
                ui.spinner();
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), &self.loading_label);
            }
        });

        // Expandable BibTeX Preview Drawer (shown right after export)
        if self.show_bibtex_drawer {
            if let Some(content) = &self.last_exported_bibtex {
                ui.add_space(6.0);
                ui.group(|ui| {
                    ui.horizontal(|ui| {
                        ui.strong("📋 Vista Previa del BibTeX Exportado:");
                        if ui.button("📋 Copiar BibTeX").clicked() {
                            ui.ctx().copy_text(content.clone());
                            self.status_message = "BibTeX copiado al portapapeles.".to_string();
                        }
                        if ui.button("❌ Cerrar").clicked() {
                            self.show_bibtex_drawer = false;
                        }
                    });
                    egui::ScrollArea::vertical().id_salt("bibtex_drawer_scroll").max_height(140.0).show(ui, |ui| {
                        ui.monospace(content);
                    });
                });
            }
        }

        // Render Retrieved Papers List
        if !self.papers.is_empty() {
            ui.add_space(8.0);
            ui.horizontal(|ui| {
                ui.heading(format!("Resultados Recuperados ({} en total):", self.total_results));
            });

            let papers_list = self.papers.clone();
            let mut style_to_copy: Option<(String, usize)> = None;

            egui::ScrollArea::vertical().id_salt("search_results_scroll").max_height(350.0).show(ui, |ui| {
                for (idx, p) in papers_list.iter().enumerate() {
                    ui.group(|ui| {
                        ui.horizontal(|ui| {
                            ui.colored_label(egui::Color32::from_rgb(59, 130, 246), format!("[{}]", p.year));
                            ui.strong(&p.title);
                            ui.colored_label(egui::Color32::GRAY, format!("({})", p.doc_type));
                        });
                        ui.horizontal(|ui| {
                            ui.label(format!("Autores: {}", p.authors.join(", ")));
                            ui.label("·");
                            ui.label(format!("Publicación: {}", p.venue));
                        });
                        if !p.doi.is_empty() {
                            ui.horizontal(|ui| {
                                ui.monospace(format!("DOI: {}", p.doi));
                                if !p.url.is_empty() {
                                    ui.hyperlink_to("🔗 Ver en portal", &p.url);
                                }
                            });
                        }
                        if !p.abstract_text.is_empty() {
                            ui.label(format!("Resumen: {}", p.abstract_text));
                        }
                        ui.horizontal(|ui| {
                            ui.label("Cita Rápida:");
                            ui.selectable_value(&mut self.selected_citation_style, "ieee".to_string(), "IEEE");
                            ui.selectable_value(&mut self.selected_citation_style, "apa7".to_string(), "APA 7");
                            ui.selectable_value(&mut self.selected_citation_style, "bibitem".to_string(), "LaTeX");
                            if ui.button(format!("📋 Copiar ({})", self.selected_citation_style.to_uppercase())).clicked() {
                                style_to_copy = Some((self.selected_citation_style.clone(), idx));
                            }
                        });
                    });
                    ui.add_space(3.0);
                }
            });

            if let Some((style, idx)) = style_to_copy {
                if let Some(target_paper) = papers_list.get(idx) {
                    let formatted = Self::format_citation_for_paper(target_paper, &style);
                    ui.ctx().copy_text(formatted);
                    self.add_toast("Cita copiada al portapapeles", false);
                }
            }
        }
    }

    fn render_exports_viewer_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("📁 Visor de Exportaciones & Metadatos BibTeX / CSV / RIS");
        ui.label("Explora, inspecciona la sintaxis de citas y copia entradas directamente sin salir de la aplicación.");

        ui.horizontal(|ui| {
            if ui.button("🔄 Refrescar Exportaciones").clicked() {
                self.exports_list = get_recent_exports(50);
                self.status_message = format!("Se encontraron {} exportaciones registradas.", self.exports_list.len());
            }

            if ui.button("📂 Abrir Carpeta exports/ en Administrador").clicked() {
                let _ = std::process::Command::new("xdg-open")
                    .arg("/home/glender/Proyectos/MCPCONECCT/exports")
                    .spawn();
            }

            ui.separator();
            ui.label("Estilo de Cita Rápida:");
            ui.selectable_value(&mut self.selected_citation_style, "ieee".to_string(), "IEEE");
            ui.selectable_value(&mut self.selected_citation_style, "apa7".to_string(), "APA 7");
            ui.selectable_value(&mut self.selected_citation_style, "bibitem".to_string(), "LaTeX BibItem");
        });

        ui.add_space(8.0);

        if self.exports_list.is_empty() {
            ui.colored_label(egui::Color32::GRAY, "No hay archivos exportados aún. Realiza una búsqueda y pulsa 'Exportar a BibTeX', 'CSV' o 'RIS'.");
            return;
        }

        // Two-column master-detail layout
        ui.columns(2, |cols| {
            // Left Column: List of Exports
            cols[0].group(|ui| {
                ui.strong("Archivos Exportados:");
                egui::ScrollArea::vertical().id_salt("exports_list_scroll").max_height(480.0).show(ui, |ui| {
                    for exp in &self.exports_list {
                        let is_selected = self.selected_export.as_ref().map(|s| s.id) == Some(exp.id);
                        let badge = if exp.format == "bib" || exp.format == "bibtex" {
                            "📚 BIB"
                        } else if exp.format == "ris" {
                            "📑 RIS"
                        } else {
                            "📊 CSV"
                        };
                        let label = format!("{} {} ({} hits) - {}", badge, exp.filename, exp.record_count, exp.database.to_uppercase());

                        if ui.selectable_label(is_selected, label).clicked() {
                            self.selected_export = Some(exp.clone());
                            if let Ok(c) = std::fs::read_to_string(&exp.file_path) {
                                self.selected_export_content = c;
                            } else {
                                self.selected_export_content = "Error al leer el archivo desde el disco.".to_string();
                            }
                        }
                    }
                });
            });

            // Right Column: File Content & Actions
            cols[1].group(|ui| {
                if let Some(exp) = &self.selected_export {
                    ui.horizontal(|ui| {
                        ui.heading(&exp.filename);
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if ui.button("📋 Copiar Contenido").clicked() {
                                ui.ctx().copy_text(self.selected_export_content.clone());
                                self.status_message = format!("Contenido de {} copiado al portapapeles.", exp.filename);
                            }
                        });
                    });

                    ui.horizontal(|ui| {
                        ui.colored_label(egui::Color32::LIGHT_BLUE, format!("Formato: {} | Registros: {} | Base: {}", exp.format.to_uppercase(), exp.record_count, exp.database.to_uppercase()));
                        ui.label(format!("· Fecha: {}", exp.timestamp));
                    });

                    ui.separator();
                    ui.strong("Contenido del Archivo:");
                    egui::ScrollArea::both().id_salt("export_content_scroll").max_height(400.0).show(ui, |ui| {
                        ui.monospace(&self.selected_export_content);
                    });
                } else {
                    ui.label("Selecciona un archivo de la lista para ver su contenido.");
                }
            });
        });
    }

    fn render_audit_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Auditoría Central de Agentes (Codex, Claude Code, Antigravity)");
        ui.label("Trazabilidad en vivo de cada consulta enviada al servidor MCP.");

        if ui.button("🔄 Refrescar Historial").clicked() {
            self.history = get_recent_history(50);
            self.status_message = format!("Historial actualizado: {} llamadas registradas.", self.history.len());
        }

        ui.add_space(8.0);
        egui::ScrollArea::vertical().id_salt("agent_audit_scroll").show(ui, |ui| {
            for rec in &self.history {
                ui.group(|ui| {
                    ui.horizontal(|ui| {
                        ui.colored_label(egui::Color32::from_rgb(168, 85, 247), &rec.agent_name);
                        ui.label("en");
                        ui.strong(&rec.database.to_uppercase());
                        ui.label(format!("· {} hits ({} ms)", rec.total_hits, rec.execution_time_ms));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.label(&rec.timestamp);
                        });
                    });
                    ui.monospace(&rec.query);
                });
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_paper_item_deserialization_with_int_year_and_nulls() {
        let json_data = serde_json::json!({
            "record_id": "54cef1ebea0f0eff93f16de3",
            "doi": "10.1109/tifs.2024.3421273",
            "title": "Semantic Deep Hiding for Robust Unlearnable Examples",
            "authors": ["Ruohan Meng", "Chenyu Yi"],
            "year": 2024,
            "venue": "IEEE Transactions",
            "doc_type": "IEEE Journals",
            "abstract": "Ensuring data privacy...",
            "url": "https://ieeexplore.ieee.org/document/10578062/",
            "sources": ["ieee"],
            "database": "ieee"
        });

        let paper: PaperItem = serde_json::from_value(json_data).expect("Should deserialize paper with int year");
        assert_eq!(paper.title, "Semantic Deep Hiding for Robust Unlearnable Examples");
        assert_eq!(paper.year, "2024");
        assert_eq!(paper.authors.len(), 2);
        assert_eq!(paper.doi, "10.1109/tifs.2024.3421273");
        assert_eq!(paper.abstract_text, "Ensuring data privacy...");

        // Test with nulls
        let json_nulls = serde_json::json!({
            "title": "Null Fields Paper",
            "year": null,
            "doi": null,
            "venue": null,
            "abstract": null,
            "authors": null
        });
        let paper_nulls: PaperItem = serde_json::from_value(json_nulls).expect("Should handle null fields");
        assert_eq!(paper_nulls.title, "Null Fields Paper");
        assert_eq!(paper_nulls.year, "");
        assert_eq!(paper_nulls.doi, "");
        assert_eq!(paper_nulls.authors.is_empty(), true);
    }
}
