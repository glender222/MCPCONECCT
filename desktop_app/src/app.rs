use std::sync::mpsc::{channel, Receiver, Sender};
use eframe::egui;
use serde::Deserialize;
use crate::burp_launcher::{is_burp_proxy_running, launch_browser_for_platform};
use crate::firefox_extractor::extract_cookies_from_firefox;
use crate::pico_translator::{translate_pico_query, TranslationResult};
use crate::db_client::{get_recent_history, get_recent_exports, SearchRecord, ExportRecord};

#[derive(PartialEq, Clone, Copy, Debug)]
pub enum ActiveTab {
    Project,
    Search,
    Library,
    NotesEvidence,
    Interchange,
    History,
    Connections,
    Calibration,
    ExportsViewer,
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

    // Block 2 Research State
    pub projects_list: Vec<crate::research_client::ProjectItem>,
    pub selected_project_idx: usize,
    pub new_project_name: String,
    pub new_project_desc: String,
    pub new_project_type: String,
    pub show_create_project_modal: bool,
    pub backend_online: bool,
    pub backend_error: Option<String>,

    // Project View Outline
    pub outline_data: Option<crate::research_client::OutlineData>,
    pub new_question_text: String,
    pub new_objective_text: String,

    // Library View
    pub library_papers: Vec<crate::research_client::PublicationDetail>,
    pub library_q: String,
    pub library_status_filter: String,
    pub selected_library_paper_id: Option<String>,

    // Notes & Evidence View
    pub annotations_list: Vec<crate::research_client::AnnotationItem>,
    pub new_annot_kind: String,
    pub new_annot_source_kind: String,
    pub new_annot_locator: String,
    pub new_annot_body: String,
    pub new_annot_question_id: String,

    // Interchange View
    pub import_file_content: String,
    pub import_file_format: String,
    pub import_preview: Option<crate::research_client::ImportPreviewData>,
    pub export_scope: String,
    pub export_format: String,
    pub export_output_text: String,

    // History View
    pub project_events: Vec<crate::research_client::EventItem>,
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

            projects_list: Vec::new(),
            selected_project_idx: 0,
            new_project_name: String::new(),
            new_project_desc: String::new(),
            new_project_type: "Systematic Literature Review".to_string(),
            show_create_project_modal: false,
            backend_online: true,
            backend_error: None,

            outline_data: None,
            new_question_text: String::new(),
            new_objective_text: String::new(),

            library_papers: Vec::new(),
            library_q: String::new(),
            library_status_filter: "ALL".to_string(),
            selected_library_paper_id: None,

            annotations_list: Vec::new(),
            new_annot_kind: "NOTE".to_string(),
            new_annot_source_kind: "NONE".to_string(),
            new_annot_locator: String::new(),
            new_annot_body: String::new(),
            new_annot_question_id: String::new(),

            import_file_content: String::new(),
            import_file_format: "bib".to_string(),
            import_preview: None,
            export_scope: "ALL".to_string(),
            export_format: "BIB".to_string(),
            export_output_text: String::new(),

            project_events: Vec::new(),
        };

        app.refresh_projects();

        if std::env::var("MCPCONECCT_AUTO_SEARCH").is_ok() {
            app.trigger_async_search();
        }

        app
    }
}

impl McpDesktopApp {
    pub fn refresh_projects(&mut self) {
        match crate::research_client::ResearchClient::list_projects() {
            Ok(projects) => {
                self.backend_online = true;
                self.backend_error = None;
                self.projects_list = projects;
                if self.selected_project_idx >= self.projects_list.len() && !self.projects_list.is_empty() {
                    self.selected_project_idx = 0;
                }
                self.refresh_active_project_data();
            }
            Err(e) => {
                self.backend_online = false;
                self.backend_error = Some(e.clone());
                self.status_message = format!("⚠️ Servicio local no disponible: {}", e);
            }
        }
    }

    pub fn get_active_project(&self) -> Option<&crate::research_client::ProjectItem> {
        self.projects_list.get(self.selected_project_idx)
    }

    pub fn get_active_project_id(&self) -> Option<String> {
        self.projects_list.get(self.selected_project_idx).map(|p| p.project_id.clone())
    }

    pub fn refresh_active_project_data(&mut self) {
        let Some(pid) = self.get_active_project_id() else {
            self.outline_data = None;
            self.library_papers.clear();
            self.annotations_list.clear();
            self.project_events.clear();
            return;
        };

        // Outline
        if let Ok(outline) = crate::research_client::ResearchClient::get_outline(&pid) {
            self.outline_data = Some(outline);
        }

        // Library
        let status_filter = if self.library_status_filter == "ALL" {
            None
        } else {
            Some(self.library_status_filter.as_str())
        };
        if let Ok(papers) = crate::research_client::ResearchClient::list_publications(&pid, &self.library_q, status_filter) {
            self.library_papers = papers;
        }

        // Annotations
        if let Ok(annots) = crate::research_client::ResearchClient::list_annotations(&pid, self.selected_library_paper_id.as_deref()) {
            self.annotations_list = annots;
        }

        // Events
        if let Ok(events) = crate::research_client::ResearchClient::list_events(&pid) {
            self.project_events = events;
        }
    }

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
                let mut visuals = egui::Visuals::dark();
                visuals.panel_fill = egui::Color32::from_rgb(18, 20, 26);
                visuals.window_fill = egui::Color32::from_rgb(24, 26, 34);
                ctx.set_visuals(visuals);
            }
            AppTheme::AcademicLight => {
                let mut visuals = egui::Visuals::light();
                visuals.panel_fill = egui::Color32::from_rgb(248, 249, 252);
                visuals.window_fill = egui::Color32::from_rgb(255, 255, 255);
                ctx.set_visuals(visuals);
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
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "● INSTITUCIONAL ACTIVO");
            }
            "VALID_PUBLIC" => {
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), "● ACCESO PÚBLICO / OPEN ACCESS");
            }
            "WAF_CHALLENGE" => {
                ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "● DESAFÍO WAF / BLOQUEO DETECTADO");
            }
            "SESSION_EXPIRED" => {
                ui.colored_label(egui::Color32::from_rgb(234, 179, 8), "● SESIÓN EXPIRADA / LOGIN REQUERIDO");
            }
            _ => {
                ui.colored_label(egui::Color32::GRAY, "● ESTADO NO VERIFICADO");
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

        // Left Sidebar Panel (ChatGPT-style Navigation & Project Drawer)
        egui::Panel::left("sidebar_panel")
            .default_size(270.0)
            .show_separator_line(true)
            .show(ui, |ui| {
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("MCPCONECCT").size(16.0).strong().color(egui::Color32::WHITE));
                    ui.colored_label(egui::Color32::from_rgb(59, 130, 246), "v2.0");
                });
                ui.label(egui::RichText::new("Academic Research Workspace").size(11.0).color(egui::Color32::from_rgb(148, 163, 184)));
                ui.add_space(10.0);

                // Section 1: PROYECTOS (ChatGPT-style vertical list)
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("PROYECTOS").strong().size(11.0).color(egui::Color32::from_rgb(148, 163, 184)));
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if ui.button("+ Nuevo").clicked() {
                            self.show_create_project_modal = true;
                        }
                    });
                });
                ui.add_space(4.0);

                let mut project_changed = false;
                if self.projects_list.is_empty() {
                    ui.colored_label(egui::Color32::from_rgb(234, 179, 8), "Sin proyectos aún. Pulsa '+ Nuevo'.");
                } else {
                    egui::ScrollArea::vertical().id_salt("sidebar_projects_scroll").max_height(140.0).show(ui, |ui| {
                        let count = self.projects_list.len();
                        for i in 0..count {
                            let (name, archived) = {
                                let p = &self.projects_list[i];
                                (p.name.clone(), p.archived)
                            };
                            let is_selected = self.selected_project_idx == i;
                            let text = if archived {
                                format!("• {} [Archivado]", name)
                            } else {
                                format!("• {}", name)
                            };
                            let rich = if is_selected {
                                egui::RichText::new(text).color(egui::Color32::WHITE).strong()
                            } else {
                                egui::RichText::new(text).color(egui::Color32::from_rgb(180, 185, 200))
                            };
                            if ui.selectable_label(is_selected, rich).clicked() {
                                self.selected_project_idx = i;
                                project_changed = true;
                            }
                        }
                    });
                }
                if project_changed {
                    self.refresh_active_project_data();
                }

                ui.add_space(8.0);
                ui.separator();
                ui.add_space(6.0);

                // Section 2: ESPACIO DE INVESTIGACIÓN (Vertical Navigation Menu)
                ui.label(egui::RichText::new("INVESTIGACIÓN").strong().size(11.0).color(egui::Color32::from_rgb(148, 163, 184)));
                ui.add_space(4.0);

                let nav_items = [
                    (ActiveTab::Project, "Alcance & Preguntas (RQs)"),
                    (ActiveTab::Search, "Búsqueda Multi-Base"),
                    (ActiveTab::Library, "Biblioteca del Proyecto"),
                    (ActiveTab::NotesEvidence, "Notas y Evidencia"),
                    (ActiveTab::Interchange, "Importar / Exportar"),
                    (ActiveTab::History, "Historial & Auditoría"),
                ];

                for (tab, label) in nav_items {
                    let is_active = self.active_tab == tab;
                    let text = if is_active {
                        egui::RichText::new(format!("  {}  ", label)).color(egui::Color32::WHITE).strong()
                    } else {
                        egui::RichText::new(format!("  {}  ", label)).color(egui::Color32::from_rgb(190, 195, 210))
                    };
                    if ui.selectable_label(is_active, text).clicked() {
                        self.active_tab = tab;
                    }
                }

                ui.add_space(8.0);
                ui.separator();
                ui.add_space(6.0);

                // Section 3: HERRAMIENTAS Y CONEXIÓN
                ui.label(egui::RichText::new("HERRAMIENTAS").strong().size(11.0).color(egui::Color32::from_rgb(148, 163, 184)));
                ui.add_space(4.0);

                let tool_items = [
                    (ActiveTab::Connections, "Conexiones & Burp Suite"),
                    (ActiveTab::Calibration, "Calibrador PICO & RSL"),
                    (ActiveTab::ExportsViewer, "Visor de Exportaciones"),
                ];

                for (tab, label) in tool_items {
                    let is_active = self.active_tab == tab;
                    let text = if is_active {
                        egui::RichText::new(format!("  {}  ", label)).color(egui::Color32::WHITE).strong()
                    } else {
                        egui::RichText::new(format!("  {}  ", label)).color(egui::Color32::from_rgb(190, 195, 210))
                    };
                    if ui.selectable_label(is_active, text).clicked() {
                        self.active_tab = tab;
                    }
                }

                // Sidebar Footer pinned to bottom
                ui.with_layout(egui::Layout::bottom_up(egui::Align::Min), |ui| {
                    ui.add_space(8.0);

                    // Theme switch button
                    let theme_btn_text = match self.theme {
                        AppTheme::DarkModern => "Modo Claro",
                        AppTheme::AcademicLight => "Modo Oscuro",
                    };
                    if ui.button(theme_btn_text).clicked() {
                        self.theme = match self.theme {
                            AppTheme::DarkModern => AppTheme::AcademicLight,
                            AppTheme::AcademicLight => AppTheme::DarkModern,
                        };
                    }

                    ui.separator();

                    // Burp status
                    ui.horizontal(|ui| {
                        if self.burp_running {
                            ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "● Burp Activo");
                        } else {
                            ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "● Burp Inactivo");
                        }
                        if ui.small_button("↻").clicked() {
                            self.burp_running = is_burp_proxy_running();
                        }
                    });

                    // Backend Connectivity Status
                    ui.horizontal(|ui| {
                        if self.backend_online {
                            ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "● Backend Conectado");
                        } else {
                            ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "● Desconectado");
                            if ui.small_button("↻").clicked() {
                                self.refresh_projects();
                            }
                        }
                    });

                    if self.is_searching || self.is_exporting || self.is_ingesting {
                        ui.horizontal(|ui| {
                            ui.spinner();
                            ui.colored_label(egui::Color32::from_rgb(59, 130, 246), &self.loading_label);
                        });
                    }
                });
            });

        // Bottom Status Bar
        egui::Panel::bottom("bottom_panel").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Estado:").strong());
                let status_color = if self.status_message.starts_with('✓') || self.status_message.starts_with('✅') {
                    egui::Color32::from_rgb(34, 197, 94)
                } else if self.status_message.starts_with('✗') || self.status_message.starts_with('❌') {
                    egui::Color32::from_rgb(239, 68, 68)
                } else {
                    egui::Color32::LIGHT_BLUE
                };
                ui.colored_label(status_color, &self.status_message);
            });
        });

        // Main Central Panel (Clean Modern Content Area)
        egui::CentralPanel::default().show(ui, |ui| {
            // Elegant context header
            ui.horizontal(|ui| {
                let title = match self.active_tab {
                    ActiveTab::Project => "Alcance del Proyecto & Preguntas de Investigación",
                    ActiveTab::Search => "Búsqueda Avanzada Multi-Filtro & Ingesta al Corpus",
                    ActiveTab::Library => "Biblioteca de Referencias del Proyecto",
                    ActiveTab::NotesEvidence => "Notas de Lectura & Síntesis de Evidencia",
                    ActiveTab::Interchange => "Intercambio: Importación y Exportación",
                    ActiveTab::History => "Historial de Auditoría & Trazabilidad",
                    ActiveTab::Connections => "Conexiones & Sesiones Burp Suite",
                    ActiveTab::Calibration => "Calibrador de Ecuaciones PICO & RSL",
                    ActiveTab::ExportsViewer => "Visor de Archivos Exportados",
                };

                ui.heading(title);

                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if let Some(active_p) = self.get_active_project() {
                        ui.colored_label(egui::Color32::from_rgb(59, 130, 246), format!("• {}", active_p.name));
                        ui.label(egui::RichText::new("Proyecto activo:").color(egui::Color32::from_rgb(148, 163, 184)));
                    } else {
                        ui.colored_label(egui::Color32::from_rgb(234, 179, 8), "Sin proyecto activo");
                    }
                });
            });
            ui.separator();
            ui.add_space(4.0);

            egui::ScrollArea::vertical()
                .id_salt("central_content_scroll")
                .auto_shrink([false, false])
                .show(ui, |ui| {
                    match self.active_tab {
                        ActiveTab::Project => self.render_project_tab(ui),
                        ActiveTab::Search => self.render_search_tab(ui),
                        ActiveTab::Library => self.render_library_tab(ui),
                        ActiveTab::NotesEvidence => self.render_notes_evidence_tab(ui),
                        ActiveTab::Interchange => self.render_interchange_tab(ui),
                        ActiveTab::History => self.render_history_tab(ui),
                        ActiveTab::Connections => self.render_connections_tab(ui),
                        ActiveTab::Calibration => self.render_calibration_tab(ui),
                        ActiveTab::ExportsViewer => self.render_exports_viewer_tab(ui),
                    }
                });
        });

        // Create Project Modal Window
        if self.show_create_project_modal {
            egui::Window::new("+ Crear Nuevo Proyecto de Investigación")
                .collapsible(false)
                .resizable(false)
                .show(ui.ctx(), |ui| {
                    ui.label("Nombre del Proyecto (1-120 caracteres):");
                    ui.text_edit_singleline(&mut self.new_project_name);

                    ui.label("Tipo de Investigación (ej. Systematic Literature Review):");
                    ui.text_edit_singleline(&mut self.new_project_type);

                    ui.label("Descripción del Proyecto:");
                    ui.text_edit_multiline(&mut self.new_project_desc);

                    ui.add_space(8.0);
                    ui.horizontal(|ui| {
                        if ui.button("Crear Proyecto").clicked() {
                            let name = self.new_project_name.trim();
                            if name.is_empty() {
                                self.add_toast("El nombre no puede estar vacío", true);
                            } else {
                                match crate::research_client::ResearchClient::create_project(name, &self.new_project_desc, &self.new_project_type) {
                                    Ok(proj) => {
                                        self.add_toast(format!("Proyecto '{}' creado", proj.name), false);
                                        self.show_create_project_modal = false;
                                        self.new_project_name.clear();
                                        self.new_project_desc.clear();
                                        self.refresh_projects();
                                        if let Some(pos) = self.projects_list.iter().position(|p| p.project_id == proj.project_id) {
                                            self.selected_project_idx = pos;
                                            self.refresh_active_project_data();
                                        }
                                    }
                                    Err(e) => {
                                        self.add_toast(format!("Error: {}", e), true);
                                    }
                                }
                            }
                        }
                        if ui.button("Cancelar").clicked() {
                            self.show_create_project_modal = false;
                        }
                    });
                });
        }

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
    fn render_project_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("📁 Gestión de Proyecto, Preguntas y Objetivos");
        ui.label("Define el alcance, formula preguntas de investigación (RQs) y objetivos alineados.");
        ui.add_space(6.0);

        if !self.backend_online {
            ui.group(|ui| {
                ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "⚠️ Servicio local no disponible.");
                ui.label("No se pudo conectar con el servidor backend en http://127.0.0.1:8765.");
                if let Some(err) = &self.backend_error {
                    ui.monospace(err);
                }
                if ui.button("🔄 Reintentar Conexión").clicked() {
                    self.refresh_projects();
                }
            });
            return;
        }

        if self.projects_list.is_empty() {
            ui.group(|ui| {
                ui.label("No se han creado proyectos aún.");
                if ui.button("➕ Crear Primer Proyecto").clicked() {
                    self.show_create_project_modal = true;
                }
            });
            return;
        }

        if self.selected_project_idx >= self.projects_list.len() {
            self.selected_project_idx = 0;
        }

        let p_orig = self.projects_list[self.selected_project_idx].clone();
        let pid = p_orig.project_id.clone();
        let rev = p_orig.revision;
        let is_archived = p_orig.archived;

        // Project Metadata Box
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.strong("ID del Proyecto:");
                ui.monospace(&pid);
                ui.separator();
                ui.label(format!("Revisión: {}", rev));
                ui.separator();
                if is_archived {
                    ui.colored_label(egui::Color32::from_rgb(234, 179, 8), "● ARCHIVADO (Solo Lectura)");
                } else {
                    ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "● ACTIVO");
                }
            });

            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label("Nombre:");
                ui.text_edit_singleline(&mut self.projects_list[self.selected_project_idx].name);
            });

            ui.horizontal(|ui| {
                ui.label("Tipo de Investigación:");
                ui.text_edit_singleline(&mut self.projects_list[self.selected_project_idx].research_type);
            });

            ui.label("Descripción del Proyecto:");
            ui.text_edit_multiline(&mut self.projects_list[self.selected_project_idx].description);

            ui.horizontal(|ui| {
                if ui.button("Guardar Metadatos").clicked() {
                    let cur_name = self.projects_list[self.selected_project_idx].name.clone();
                    let cur_desc = self.projects_list[self.selected_project_idx].description.clone();
                    match crate::research_client::ResearchClient::update_project(&pid, &cur_name, &cur_desc, None, rev) {
                        Ok(updated) => {
                            self.add_toast("Metadatos de proyecto guardados", false);
                            self.projects_list[self.selected_project_idx] = updated;
                        }
                        Err(e) => {
                            self.add_toast(format!("Error guardando: {}", e), true);
                        }
                    }
                }

                if is_archived {
                    if ui.button("Desarchivar Proyecto").clicked() {
                        let cur_name = self.projects_list[self.selected_project_idx].name.clone();
                        let cur_desc = self.projects_list[self.selected_project_idx].description.clone();
                        match crate::research_client::ResearchClient::update_project(&pid, &cur_name, &cur_desc, Some(false), rev) {
                            Ok(updated) => {
                                self.add_toast("Proyecto desarchivado", false);
                                self.projects_list[self.selected_project_idx] = updated;
                            }
                            Err(e) => self.add_toast(format!("Error: {}", e), true),
                        }
                    }
                } else {
                    if ui.button("Archivar Proyecto").clicked() {
                        let cur_name = self.projects_list[self.selected_project_idx].name.clone();
                        let cur_desc = self.projects_list[self.selected_project_idx].description.clone();
                        match crate::research_client::ResearchClient::update_project(&pid, &cur_name, &cur_desc, Some(true), rev) {
                            Ok(updated) => {
                                self.add_toast("Proyecto archivado", false);
                                self.projects_list[self.selected_project_idx] = updated;
                            }
                            Err(e) => self.add_toast(format!("Error: {}", e), true),
                        }
                    }
                }

                if ui.button("Recargar desde Servidor").clicked() {
                    self.refresh_projects();
                }
            });
        });

        ui.add_space(8.0);

        // Questions & Objectives Outline
        if self.outline_data.is_none() {
            if let Ok(outline) = crate::research_client::ResearchClient::get_outline(&pid) {
                self.outline_data = Some(outline);
            }
        }

        let mut remove_q_idx = None;
        let mut remove_o_idx = None;

        ui.columns(2, |cols| {
            // Questions column
            cols[0].group(|ui| {
                ui.heading("Preguntas de Investigación (RQs)");
                if let Some(outline) = &self.outline_data {
                    for (idx, q) in outline.questions.iter().enumerate() {
                        ui.horizontal(|ui| {
                            ui.strong(format!("RQ{}:", idx + 1));
                            ui.label(&q.text);
                            if ui.button("×").clicked() {
                                remove_q_idx = Some(idx);
                            }
                        });
                    }
                }

                ui.separator();
                ui.horizontal(|ui| {
                    ui.text_edit_singleline(&mut self.new_question_text);
                    if ui.button("+ Añadir RQ").clicked() {
                        let text = self.new_question_text.trim().to_string();
                        if !text.is_empty() {
                            if let Some(outline) = &mut self.outline_data {
                                let pos = outline.questions.len() as i64;
                                outline.questions.push(crate::research_client::QuestionItem {
                                    question_id: None,
                                    text,
                                    position: pos,
                                    revision: 1,
                                });
                                self.new_question_text.clear();
                            }
                        }
                    }
                });
            });

            // Objectives column
            cols[1].group(|ui| {
                ui.heading("Objetivos de Investigación (OBJs)");
                if let Some(outline) = &self.outline_data {
                    for (idx, obj) in outline.objectives.iter().enumerate() {
                        ui.horizontal(|ui| {
                            ui.strong(format!("OBJ{}:", idx + 1));
                            ui.label(&obj.text);
                            if ui.button("×").clicked() {
                                remove_o_idx = Some(idx);
                            }
                        });
                    }
                }

                ui.separator();
                ui.horizontal(|ui| {
                    ui.text_edit_singleline(&mut self.new_objective_text);
                    if ui.button("+ Añadir OBJ").clicked() {
                        let text = self.new_objective_text.trim().to_string();
                        if !text.is_empty() {
                            if let Some(outline) = &mut self.outline_data {
                                let pos = outline.objectives.len() as i64;
                                outline.objectives.push(crate::research_client::ObjectiveItem {
                                    objective_id: None,
                                    text,
                                    position: pos,
                                    revision: 1,
                                });
                                self.new_objective_text.clear();
                            }
                        }
                    }
                });
            });
        });

        if let Some(idx) = remove_q_idx {
            if let Some(outline) = &mut self.outline_data {
                outline.questions.remove(idx);
                for (i, q) in outline.questions.iter_mut().enumerate() {
                    q.position = i as i64;
                }
            }
        }
        if let Some(idx) = remove_o_idx {
            if let Some(outline) = &mut self.outline_data {
                outline.objectives.remove(idx);
                for (i, o) in outline.objectives.iter_mut().enumerate() {
                    o.position = i as i64;
                }
            }
        }

        ui.add_space(6.0);
        if ui.button("💾 Guardar Esquema Completo (Preguntas y Objetivos)").clicked() {
            if let Some(outline) = &self.outline_data {
                let out_pid = outline.project_id.clone();
                let out_rev = outline.revision;
                let qs = outline.questions.clone();
                let objs = outline.objectives.clone();
                match crate::research_client::ResearchClient::set_outline(&out_pid, out_rev, qs, objs) {
                    Ok(new_outline) => {
                        self.outline_data = Some(new_outline);
                        self.add_toast("Esquema guardado exitosamente", false);
                        self.refresh_projects();
                    }
                    Err(e) => {
                        self.add_toast(format!("Error guardando esquema: {}", e), true);
                    }
                }
            }
        }
    }

    fn render_library_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("📚 Biblioteca del Proyecto");
        ui.label("Publicaciones, estados de lectura, etiquetas y colecciones asociadas.");
        ui.add_space(6.0);

        if !self.backend_online {
            ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "⚠️ Servicio local no disponible.");
            if ui.button("🔄 Reintentar").clicked() {
                self.refresh_projects();
            }
            return;
        }

        let Some(pid) = self.get_active_project_id() else {
            ui.label("Selecciona o crea un proyecto para ver su biblioteca.");
            return;
        };

        // Filter Bar
        ui.horizontal(|ui| {
            ui.label("🔍 Buscar:");
            ui.text_edit_singleline(&mut self.library_q);

            ui.separator();
            ui.label("Estado de Lectura:");
            let prev_status = self.library_status_filter.clone();
            ui.selectable_value(&mut self.library_status_filter, "ALL".to_string(), "Todos");
            ui.selectable_value(&mut self.library_status_filter, "UNREAD".to_string(), "⚪ No Leído");
            ui.selectable_value(&mut self.library_status_filter, "READING".to_string(), "🔵 Leyendo");
            ui.selectable_value(&mut self.library_status_filter, "READ".to_string(), "🟢 Leído");

            if self.library_status_filter != prev_status || ui.button("🔍 Filtrar").clicked() {
                self.refresh_active_project_data();
            }

            ui.separator();
            if ui.button("🔄 Refrescar").clicked() {
                self.refresh_active_project_data();
            }
        });

        ui.add_space(6.0);

        if self.library_papers.is_empty() {
            ui.colored_label(egui::Color32::GRAY, "No hay publicaciones en la biblioteca de este proyecto con los filtros actuales.");
            ui.label("Puedes buscar publicaciones en la pestaña 'Búsqueda' o importar referencias en 'Intercambio'.");
            return;
        }

        ui.strong(format!("Publicaciones en Biblioteca ({} encontradas):", self.library_papers.len()));

        let papers_to_render = self.library_papers.clone();
        let mut status_update: Option<(String, String)> = None;
        let mut open_notes_for: Option<String> = None;

        egui::ScrollArea::vertical().id_salt("library_papers_scroll").max_height(480.0).show(ui, |ui| {
            for p in &papers_to_render {
                ui.group(|ui| {
                    ui.horizontal(|ui| {
                        let status_badge = match p.reading_status.as_str() {
                            "READ" => "🟢 LEÍDO",
                            "READING" => "🔵 LEYENDO",
                            _ => "⚪ NO LEÍDO",
                        };
                        ui.strong(status_badge);

                        if let Some(y) = p.year {
                            ui.colored_label(egui::Color32::from_rgb(59, 130, 246), format!("[{}]", y));
                        }
                        ui.heading(&p.title);
                    });

                    ui.horizontal(|ui| {
                        if !p.authors.is_empty() {
                            ui.label(format!("Autores: {}", p.authors.join(", ")));
                        }
                        if let Some(v) = &p.venue {
                            ui.label("·");
                            ui.label(format!("Publicación: {}", v));
                        }
                    });

                    if let Some(doi) = &p.doi {
                        ui.horizontal(|ui| {
                            ui.monospace(format!("DOI: {}", doi));
                            if !p.url.is_empty() {
                                ui.hyperlink_to("🔗 Ver Enlace", &p.url);
                            }
                        });
                    }

                    // Reading status pills / transitions
                    ui.horizontal(|ui| {
                        ui.label("Cambiar Estado:");
                        if p.reading_status != "UNREAD" && ui.button("⚪ No Leído").clicked() {
                            status_update = Some((p.publication_id.clone(), "UNREAD".to_string()));
                        }
                        if p.reading_status != "READING" && ui.button("🔵 Leyendo").clicked() {
                            status_update = Some((p.publication_id.clone(), "READING".to_string()));
                        }
                        if p.reading_status != "READ" && ui.button("🟢 Leído").clicked() {
                            status_update = Some((p.publication_id.clone(), "READING".to_string()));
                        }

                        ui.separator();
                        if ui.button("📝 Ver / Añadir Notas y Evidencias").clicked() {
                            open_notes_for = Some(p.publication_id.clone());
                        }
                    });
                });
                ui.add_space(4.0);
            }
        });

        if let Some((pub_id, new_stat)) = status_update {
            let _ = crate::research_client::ResearchClient::update_reading_status(&pid, &pub_id, &new_stat);
            self.refresh_active_project_data();
        }

        if let Some(pub_id) = open_notes_for {
            self.selected_library_paper_id = Some(pub_id);
            self.active_tab = ActiveTab::NotesEvidence;
            self.refresh_active_project_data();
        }
    }

    fn render_notes_evidence_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("📝 Notas y Evidencia Textual");
        ui.label("Registra notas libres, citas textuales y paráfrasis con procedencia estricta.");
        ui.add_space(6.0);

        if !self.backend_online {
            ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "⚠️ Servicio local no disponible.");
            if ui.button("🔄 Reintentar").clicked() {
                self.refresh_projects();
            }
            return;
        }

        let Some(pid) = self.get_active_project_id() else {
            ui.label("Selecciona un proyecto para gestionar notas.");
            return;
        };

        // Publication selector
        ui.horizontal(|ui| {
            ui.label("Publicación:");
            let current_pub_title = self.library_papers.iter()
                .find(|p| Some(&p.publication_id) == self.selected_library_paper_id.as_ref())
                .map(|p| p.title.clone())
                .unwrap_or_else(|| "Todas / Ninguna seleccionada".to_string());

            let mut change_paper_to = None;
            egui::ComboBox::from_id_salt("notes_pub_selector")
                .selected_text(current_pub_title)
                .show_ui(ui, |ui| {
                    if ui.selectable_label(self.selected_library_paper_id.is_none(), "Todas las publicaciones").clicked() {
                        change_paper_to = Some(None);
                    }
                    for p in &self.library_papers {
                        let selected = Some(&p.publication_id) == self.selected_library_paper_id.as_ref();
                        if ui.selectable_label(selected, &p.title).clicked() {
                            change_paper_to = Some(Some(p.publication_id.clone()));
                        }
                    }
                });

            if let Some(target) = change_paper_to {
                self.selected_library_paper_id = target;
                self.refresh_active_project_data();
            }

            if ui.button("🔄 Refrescar Notas").clicked() {
                self.refresh_active_project_data();
            }
        });

        ui.add_space(8.0);

        // Form to add annotation
        if let Some(target_pub_id) = self.selected_library_paper_id.clone() {
            ui.group(|ui| {
                ui.strong("➕ Crear Nueva Nota o Evidencia Textual");

                ui.horizontal(|ui| {
                    ui.label("Tipo:");
                    ui.selectable_value(&mut self.new_annot_kind, "NOTE".to_string(), "📝 NOTA (Libre)");
                    ui.selectable_value(&mut self.new_annot_kind, "QUOTE".to_string(), "💬 CITA (Textual)");
                    ui.selectable_value(&mut self.new_annot_kind, "PARAPHRASE".to_string(), "💡 PARÁFRASIS");
                });

                if self.new_annot_kind == "NOTE" {
                    self.new_annot_source_kind = "NONE".to_string();
                    ui.label("Procedencia: Ninguna (Nota libre)");
                } else {
                    ui.horizontal(|ui| {
                        ui.label("Origen del Texto:");
                        ui.selectable_value(&mut self.new_annot_source_kind, "ABSTRACT".to_string(), "Resumen (Abstract)");
                        ui.selectable_value(&mut self.new_annot_source_kind, "FULLTEXT".to_string(), "Texto Completo (Fulltext)");
                    });

                    if self.new_annot_source_kind == "ABSTRACT" {
                        ui.colored_label(egui::Color32::from_rgb(59, 130, 246), "ℹ️ Etiqueta obligatoria: 'Basado en resumen' (Localizador deshabilitado).");
                    } else if self.new_annot_source_kind == "FULLTEXT" {
                        ui.horizontal(|ui| {
                            ui.label("Localizador (Obligatorio 1-200 caracteres, ej: 'p. 7, sección 3.2'):");
                            ui.text_edit_singleline(&mut self.new_annot_locator);
                        });
                    }
                }

                // Question link selector
                if let Some(outline) = &self.outline_data {
                    if !outline.questions.is_empty() {
                        ui.horizontal(|ui| {
                            ui.label("Pregunta de Investigación Vinculada:");
                            egui::ComboBox::from_id_salt("annot_question_selector")
                                .selected_text(
                                    outline.questions.iter()
                                        .find(|q| q.question_id.as_ref() == Some(&self.new_annot_question_id))
                                        .map(|q| q.text.as_str())
                                        .unwrap_or("Ninguna")
                                )
                                .show_ui(ui, |ui| {
                                    if ui.selectable_label(self.new_annot_question_id.is_empty(), "Ninguna").clicked() {
                                        self.new_annot_question_id.clear();
                                    }
                                    for q in &outline.questions {
                                        if let Some(qid) = &q.question_id {
                                            if ui.selectable_label(&self.new_annot_question_id == qid, &q.text).clicked() {
                                                self.new_annot_question_id = qid.clone();
                                            }
                                        }
                                    }
                                });
                        });
                    }
                }

                ui.label("Contenido:");
                ui.text_edit_multiline(&mut self.new_annot_body);

                if ui.button("💾 Guardar Nota / Evidencia").clicked() {
                    let body = self.new_annot_body.trim().to_string();
                    if body.is_empty() {
                        self.add_toast("El cuerpo de la nota no puede estar vacío", true);
                    } else if self.new_annot_kind != "NOTE" && self.new_annot_source_kind == "FULLTEXT" && self.new_annot_locator.trim().is_empty() {
                        self.add_toast("El localizador es obligatorio para evidencia de texto completo (FULLTEXT)", true);
                    } else {
                        let locator = if self.new_annot_kind == "NOTE" || self.new_annot_source_kind == "ABSTRACT" {
                            None
                        } else {
                            Some(self.new_annot_locator.trim())
                        };
                        let qid = if self.new_annot_question_id.is_empty() { None } else { Some(self.new_annot_question_id.as_str()) };
                        match crate::research_client::ResearchClient::create_annotation(
                            &pid,
                            &target_pub_id,
                            &self.new_annot_kind,
                            &body,
                            &self.new_annot_source_kind,
                            locator,
                            qid,
                        ) {
                            Ok(_) => {
                                self.add_toast("Anotación creada exitosamente", false);
                                self.new_annot_body.clear();
                                self.new_annot_locator.clear();
                                self.refresh_active_project_data();
                            }
                            Err(e) => {
                                self.add_toast(format!("Error: {}", e), true);
                            }
                        }
                    }
                }
            });
        } else {
            ui.label("💡 Selecciona una publicación específica arriba para añadir notas o evidencias.");
        }

        ui.add_space(8.0);
        ui.strong(format!("Anotaciones Registradas ({}):", self.annotations_list.len()));

        let annots_to_render = self.annotations_list.clone();
        egui::ScrollArea::vertical().id_salt("annotations_scroll").max_height(350.0).show(ui, |ui| {
            for a in &annots_to_render {
                ui.group(|ui| {
                    ui.horizontal(|ui| {
                        let kind_badge = match a.kind.as_str() {
                            "QUOTE" => "CITA",
                            "PARAPHRASE" => "PARÁFRASIS",
                            _ => "NOTA",
                        };
                        ui.strong(kind_badge);

                        if !a.provenance_badge.is_empty() {
                            ui.colored_label(egui::Color32::from_rgb(59, 130, 246), format!("[{}]", a.provenance_badge));
                        }

                        let actor_badge = if a.actor_type == "AGENT" {
                            format!("[AGENT] {}", a.actor_label)
                        } else {
                            format!("[HUMAN] {}", a.actor_label)
                        };
                        ui.label(actor_badge);

                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.label(format!("Rev: {} · {}", a.revision, a.created_at));
                        });
                    });

                    ui.label(&a.body);

                    if let Some(loc) = &a.locator {
                        ui.label(format!("Localizador: {}", loc));
                    }
                    if let Some(qid) = &a.question_id {
                        ui.label(format!("Enlace RQ: {}", qid));
                    }
                });
                ui.add_space(4.0);
            }
        });
    }

    fn render_interchange_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Intercambio: Importación, Exportación y Restauración");
        ui.label("Importa referencias desde BibTeX, RIS o CSV y exporta proyectos completos o bibliografías.");
        ui.add_space(6.0);

        if !self.backend_online {
            ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "● Servicio local no disponible.");
            if ui.button("Reintentar").clicked() {
                self.refresh_projects();
            }
            return;
        }

        let Some(pid) = self.get_active_project_id() else {
            ui.label("Selecciona o crea un proyecto para usar el intercambio.");
            return;
        };

        ui.columns(2, |cols| {
            // Import section
            cols[0].group(|ui| {
                ui.heading("Importar Referencias a Proyecto");
                ui.horizontal(|ui| {
                    ui.label("Formato:");
                    ui.selectable_value(&mut self.import_file_format, "bib".to_string(), "BibTeX (.bib)");
                    ui.selectable_value(&mut self.import_file_format, "ris".to_string(), "RIS (.ris)");
                    ui.selectable_value(&mut self.import_file_format, "csv".to_string(), "CSV RFC4180");
                });

                ui.label("Contenido del archivo (pegar texto o arrastrar):");
                ui.text_edit_multiline(&mut self.import_file_content);

                ui.horizontal(|ui| {
                    if ui.button("Previsualizar Importación").clicked() {
                        let content = self.import_file_content.trim();
                        if content.is_empty() {
                            self.add_toast("Pega primero el contenido a importar", true);
                        } else {
                            match crate::research_client::ResearchClient::preview_import(content, &self.import_file_format) {
                                Ok(prev) => {
                                    self.import_preview = Some(prev);
                                    self.add_toast("Previsualización generada", false);
                                }
                                Err(e) => {
                                    self.add_toast(format!("Error: {}", e), true);
                                }
                            }
                        }
                    }

                    if ui.button("Limpiar").clicked() {
                        self.import_file_content.clear();
                        self.import_preview = None;
                    }
                });

                if let Some(prev) = &self.import_preview {
                    ui.separator();
                    ui.strong("Resultado de Previsualización:");
                    ui.label(format!("Total analizado: {} registros", prev.total_parsed));
                    ui.colored_label(egui::Color32::from_rgb(34, 197, 94), format!("Válidos: {}", prev.valid_count));
                    if prev.invalid_count > 0 {
                        ui.colored_label(egui::Color32::from_rgb(239, 68, 68), format!("Rechazados: {}", prev.invalid_count));
                    }
                    ui.label(format!("Caduca: {}", prev.expires_at));

                    if prev.valid_count > 0 {
                        let prev_id = prev.preview_id.clone();
                        let f_hash = prev.file_hash.clone();
                        if ui.button("✓ Confirmar e Incorporar a la Biblioteca").clicked() {
                            match crate::research_client::ResearchClient::commit_import(&pid, &prev_id, &f_hash) {
                                Ok(_) => {
                                    self.add_toast("Importación confirmada e incorporada", false);
                                    self.import_preview = None;
                                    self.import_file_content.clear();
                                    self.refresh_active_project_data();
                                }
                                Err(e) => {
                                    self.add_toast(format!("Error en commit: {}", e), true);
                                }
                            }
                        }
                    }
                }
            });

            // Export section
            cols[1].group(|ui| {
                ui.heading("Exportar Proyecto o Bibliografía");
                ui.horizontal(|ui| {
                    ui.label("Ámbito (Scope):");
                    ui.selectable_value(&mut self.export_scope, "ALL".to_string(), "Proyecto Completo");
                });

                ui.horizontal(|ui| {
                    ui.label("Formato:");
                    ui.selectable_value(&mut self.export_format, "BIB".to_string(), "BibTeX (.bib)");
                    ui.selectable_value(&mut self.export_format, "RIS".to_string(), "RIS (.ris)");
                    ui.selectable_value(&mut self.export_format, "CSV".to_string(), "CSV RFC4180");
                    ui.selectable_value(&mut self.export_format, "PROJECT_JSON".to_string(), "PROJECT_JSON");
                });

                if ui.button("Generar Exportación").clicked() {
                    match crate::research_client::ResearchClient::export_project(&pid, &self.export_scope, &self.export_format) {
                        Ok(content) => {
                            self.export_output_text = content;
                            self.add_toast("Exportación generada", false);
                        }
                        Err(e) => {
                            self.add_toast(format!("Error al exportar: {}", e), true);
                        }
                    }
                }

                if !self.export_output_text.is_empty() {
                    ui.separator();
                    ui.horizontal(|ui| {
                        ui.strong("Salida de Exportación:");
                        if ui.button("Copiar al Portapapeles").clicked() {
                            ui.ctx().copy_text(self.export_output_text.clone());
                            self.add_toast("Copiado al portapapeles", false);
                        }
                    });
                    egui::ScrollArea::vertical().id_salt("export_preview_scroll").max_height(200.0).show(ui, |ui| {
                        ui.monospace(&self.export_output_text);
                    });
                }
            });
        });
    }

    fn render_history_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Historial y Trazabilidad de Auditoría");
        ui.label("Auditoría append-only de modificaciones del proyecto y ejecuciones de agentes.");
        ui.add_space(6.0);

        if !self.backend_online {
            ui.colored_label(egui::Color32::from_rgb(239, 68, 68), "● Servicio local no disponible.");
            if ui.button("Reintentar").clicked() {
                self.refresh_projects();
            }
            return;
        }

        ui.horizontal(|ui| {
            if ui.button("Refrescar Eventos del Proyecto").clicked() {
                self.refresh_active_project_data();
            }
        });

        ui.add_space(6.0);
        ui.strong(format!("Eventos del Proyecto Activo ({}):", self.project_events.len()));

        let events_to_render = self.project_events.clone();
        egui::ScrollArea::vertical().id_salt("project_events_scroll").max_height(280.0).show(ui, |ui| {
            for ev in &events_to_render {
                ui.group(|ui| {
                    ui.horizontal(|ui| {
                        let actor_badge = if ev.actor_type == "AGENT" {
                            format!("[AGENT] {}", ev.actor_label)
                        } else {
                            format!("[HUMAN] {}", ev.actor_label)
                        };
                        ui.colored_label(egui::Color32::from_rgb(168, 85, 247), actor_badge);

                        ui.strong(&ev.action);
                        ui.label(format!("en {} [{}]", ev.entity_type, ev.entity_id));

                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.label(&ev.created_at);
                        });
                    });
                });
                ui.add_space(2.0);
            }
        });

        ui.separator();
        ui.heading("Auditoría de Consultas MCP / Búsquedas");
        if ui.button("Refrescar Consultas").clicked() {
            self.history = get_recent_history(50);
        }
        let history_to_render = self.history.clone();
        egui::ScrollArea::vertical().id_salt("history_queries_scroll").max_height(200.0).show(ui, |ui| {
            for rec in &history_to_render {
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
                ui.add_space(2.0);
            }
        });
    }

    fn render_connections_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Gestión Automatizada de Sesiones y Credenciales");
        ui.label("Captura de credenciales directa desde Firefox y navegación enrutada a través de Burp Suite.");
        ui.add_space(8.0);

        // Global Diagnostic & Health Check Bar
        ui.horizontal(|ui| {
            let diag_btn = ui.add_enabled(!self.is_diagnosing, egui::Button::new("Diagnosticar Salud de Conexiones & WAF"));
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
                ui.label("Auto-Captura Directa:");
                if ui.button("Extraer Automáticamente Sesiones desde Firefox (1-Clic)").clicked() {
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
                    if ui.button("Abrir en Burp").clicked() {
                        match launch_browser_for_platform("scopus") {
                            Ok(msg) => self.status_message = msg,
                            Err(e) => self.status_message = e,
                        }
                    }
                    if ui.button("Probar").clicked() {
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
                    if ui.button("Abrir en Burp").clicked() {
                        match launch_browser_for_platform("ieee") {
                            Ok(msg) => self.status_message = msg,
                            Err(e) => self.status_message = e,
                        }
                    }
                    if ui.button("Probar").clicked() {
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
                    if ui.button("Abrir en Burp").clicked() {
                        match launch_browser_for_platform("springer") {
                            Ok(msg) => self.status_message = msg,
                            Err(e) => self.status_message = e,
                        }
                    }
                    if ui.button("Probar").clicked() {
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
            ui.heading("Soporte de Proxy Universitario (EZProxy / OpenAthens)");
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
            if ui.button("Cargar Ecuación RSL de Perturbación Proactiva (ESM_1.tex)").clicked() {
                self.pico_p = "\"unlearnable*\", \"availability poison*\", \"perturbative availability\", \"error-minimizing noise\", \"indiscriminate poisoning\", \"image cloaking\", \"facial privacy protection\", \"unauthorized training\"".to_string();
                self.pico_i = "\"countermeasure*\", \"defens*\", \"defenc*\", \"defend*\", \"attack*\", \"break*\", \"bypass*\", \"adversarial training\", \"augment*\", \"purif*\", \"ensemble*\", \"fine-tuning\"".to_string();
                self.pico_c = "\"baseline*\", \"clean\", \"existing\", \"previous*\", \"benchmark*\", \"original data\"".to_string();
                self.pico_o = "\"accurac*\", \"performance*\", \"effective*\", \"success rate*\", \"imperceptib*\", \"generaliz*\"".to_string();
                self.translation = Some(translate_pico_query(&self.pico_p, &self.pico_i, &self.pico_c, &self.pico_o));
                self.status_message = "Ecuación de la RSL cargada y traducida.".to_string();
            }

            if ui.button("Traducir y Validar").clicked() {
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
                    ui.colored_label(egui::Color32::from_rgb(34, 197, 94), format!("✓ IEEE Xplore: {} / 10 comodines utilizados (VÁLIDO)", trans.ieee_wildcard_count));
                } else {
                    ui.colored_label(egui::Color32::from_rgb(239, 68, 68), format!("✗ IEEE Xplore: {} comodines detectados (SUPERA EL LÍMITE DE 10)", trans.ieee_wildcard_count));
                }

                // Scopus Warnings
                for w in &trans.scopus_warnings {
                    ui.colored_label(egui::Color32::GOLD, format!("Advertencia: {}", w));
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
        // Central Corpus Summary Card
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.strong("Corpus Central SLR (default_slr):");
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), format!("{} Artículos Únicos", self.corpus_summary.total_papers));
                ui.label("·");
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), format!("{} Enriquecidos DOI", self.corpus_summary.enriched_count));
                ui.label("·");
                ui.colored_label(egui::Color32::LIGHT_BLUE, format!("{} con Abstract", self.corpus_summary.with_abstract_count));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("↻ Actualizar").clicked() {
                        self.corpus_summary = crate::db_client::get_corpus_summary("default_slr");
                    }
                });
            });
        });
        ui.add_space(6.0);

        // Database and Mode Selectors Card
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Base de datos:").strong());
                ui.selectable_value(&mut self.selected_db, "ieee".to_string(), "IEEE Xplore");
                ui.selectable_value(&mut self.selected_db, "springer".to_string(), "SpringerLink");
                ui.selectable_value(&mut self.selected_db, "scopus".to_string(), "Scopus (Elsevier)");

                ui.separator();
                ui.label(egui::RichText::new("Modo:").strong());
                ui.selectable_value(&mut self.search_mode, "advanced".to_string(), "Avanzada (Booleana)");
                ui.selectable_value(&mut self.search_mode, "normal".to_string(), "Normal (Palabras clave)");

                ui.separator();
                ui.label("Rango de Años:");
                ui.add(egui::DragValue::new(&mut self.year_start).range(1990..=2030));
                ui.label("a");
                ui.add(egui::DragValue::new(&mut self.year_end).range(1990..=2030));
            });

            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Filtros por Tipo de Documento:").strong().size(11.5));
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

        ui.add_space(6.0);
        ui.label(egui::RichText::new("Consulta de Búsqueda:").strong());
        ui.text_edit_multiline(&mut self.search_query);

        ui.add_space(4.0);
        // Primary Search Actions Row
        ui.horizontal(|ui| {
            let search_btn = ui.add_enabled(
                !self.is_searching,
                egui::Button::new(egui::RichText::new("  Buscar en Base de Datos  ").strong()),
            );
            if search_btn.clicked() {
                self.trigger_async_search();
            }

            if self.is_searching {
                ui.spinner();
                ui.colored_label(egui::Color32::from_rgb(59, 130, 246), &self.loading_label);
            }

            ui.separator();
            ui.label(egui::RichText::new("Ingesta al Corpus:").color(egui::Color32::from_rgb(148, 163, 184)));
            ui.label("Lote:");
            ui.add(egui::DragValue::new(&mut self.bulk_ingest_records).range(10..=500));
            ui.checkbox(&mut self.enrich_missing_abstracts, "Enriquecer DOI");

            let ingest_btn = ui.add_enabled(!self.is_ingesting, egui::Button::new("Ingestar Streaming"));
            if ingest_btn.clicked() {
                self.trigger_async_ingest();
            }

            let dedup_btn = ui.button("Desduplicar Corpus");
            if dedup_btn.clicked() {
                self.trigger_async_deduplicate();
            }

            ui.separator();
            ui.label(egui::RichText::new("Exportar:").color(egui::Color32::from_rgb(148, 163, 184)));
            if ui.add_enabled(!self.is_exporting, egui::Button::new(".BIB")).clicked() {
                self.trigger_async_export("bibtex");
            }
            if ui.add_enabled(!self.is_exporting, egui::Button::new(".CSV")).clicked() {
                self.trigger_async_export("csv");
            }
            if ui.add_enabled(!self.is_exporting, egui::Button::new(".RIS")).clicked() {
                self.trigger_async_export("ris");
            }

            if (self.is_exporting || self.is_ingesting) && !self.is_searching {
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
                        ui.strong("Vista Previa del BibTeX Exportado:");
                        if ui.button("Copiar BibTeX").clicked() {
                            ui.ctx().copy_text(content.clone());
                            self.status_message = "BibTeX copiado al portapapeles.".to_string();
                        }
                        if ui.button("Cerrar").clicked() {
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
            ui.add_space(10.0);
            ui.horizontal(|ui| {
                ui.heading(format!("Resultados Recuperados ({} en total):", self.total_results));
            });

            let papers_list = self.papers.clone();
            let mut style_to_copy: Option<(String, usize)> = None;

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
                                ui.hyperlink_to("Ver en portal ›", &p.url);
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
                        if ui.button(format!("Copiar ({})", self.selected_citation_style.to_uppercase())).clicked() {
                            style_to_copy = Some((self.selected_citation_style.clone(), idx));
                        }
                    });
                });
                ui.add_space(4.0);
            }

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
        ui.heading("Visor de Exportaciones & Metadatos BibTeX / CSV / RIS");
        ui.label("Explora, inspecciona la sintaxis de citas y copia entradas directamente sin salir de la aplicación.");

        ui.horizontal(|ui| {
            if ui.button("Refrescar Exportaciones").clicked() {
                self.exports_list = get_recent_exports(50);
                self.status_message = format!("Se encontraron {} exportaciones registradas.", self.exports_list.len());
            }

            if ui.button("Abrir Carpeta exports/ en Administrador").clicked() {
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
                            "[BIB]"
                        } else if exp.format == "ris" {
                            "[RIS]"
                        } else {
                            "[CSV]"
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
                            if ui.button("Copiar Contenido").clicked() {
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
