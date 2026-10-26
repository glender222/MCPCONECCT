use std::sync::mpsc::{channel, Receiver, Sender};
use eframe::egui;
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

#[derive(Clone, Debug, Default, serde::Deserialize, serde::Serialize)]
pub struct PaperItem {
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub authors: Vec<String>,
    #[serde(default)]
    pub year: String,
    #[serde(default)]
    pub doi: String,
    #[serde(default)]
    pub venue: String,
    #[serde(default)]
    pub doc_type: String,
    #[serde(alias = "abstract", default)]
    pub abstract_text: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub database: String,
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

        Self {
            event_tx: tx,
            event_rx: rx,
            active_tab: ActiveTab::Search,
            theme: AppTheme::DarkModern,
            status_message: "MCPCONECCT Desktop Hub listo. Selecciona una acción.".to_string(),
            burp_running: is_burp_proxy_running(),
            is_searching: false,
            is_exporting: false,
            loading_label: String::new(),

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
        }
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
                    } else {
                        self.status_message = format!("❌ {}: {}", db.to_uppercase(), message);
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
                                    if let Ok(paper) = serde_json::from_value::<PaperItem>(item.clone()) {
                                        papers.push(paper);
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
    }
}

impl McpDesktopApp {
    fn render_connections_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("Gestión Automatizada de Sesiones y Credenciales");
        ui.label("Captura de credenciales directa desde Firefox y navegación enrutada a través de Burp Suite.");
        ui.add_space(8.0);

        // One-Click Firefox Auto-Extractor
        ui.group(|ui| {
            ui.horizontal(|ui| {
                ui.label("🦊 Auto-Captura Directa:");
                if ui.button("⚡ Extraer Automáticamente Sesiones desde Firefox (1-Clic)").clicked() {
                    match extract_cookies_from_firefox() {
                        Ok(res) => {
                            self.status_message = res.message;
                        }
                        Err(err) => {
                            self.status_message = format!("Error: {}", err);
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
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "✅ Sesión Capturada (Firefox)");
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
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "✅ Conectado y Verificado");
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
                ui.colored_label(egui::Color32::from_rgb(34, 197, 94), "✅ Acceso Abierto (Sin Login)");
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
                ui.colored_label(egui::Color32::GRAY, "Sin acceso institucional (Excluido)");
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
        ui.heading("Búsqueda Avanzada Multi-Filtro en Vivo (No Bloqueante)");

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
            let search_btn = ui.add_enabled(!self.is_searching, egui::Button::new("🔍 Ejecutar Búsqueda en Vivo"));
            if search_btn.clicked() {
                self.trigger_async_search();
            }

            // Export buttons
            let exp_bib_btn = ui.add_enabled(!self.is_exporting, egui::Button::new("📥 Exportar a BibTeX"));
            if exp_bib_btn.clicked() {
                self.trigger_async_export("bibtex");
            }

            let exp_csv_btn = ui.add_enabled(!self.is_exporting, egui::Button::new("📥 Exportar a CSV"));
            if exp_csv_btn.clicked() {
                self.trigger_async_export("csv");
            }

            if self.is_searching || self.is_exporting {
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

            egui::ScrollArea::vertical().id_salt("search_results_scroll").max_height(350.0).show(ui, |ui| {
                for p in &self.papers {
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
                    });
                    ui.add_space(3.0);
                }
            });
        }
    }

    fn render_exports_viewer_tab(&mut self, ui: &mut egui::Ui) {
        ui.heading("📁 Visor de Exportaciones & Metadatos BibTeX / CSV In-App");
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
        });

        ui.add_space(8.0);

        if self.exports_list.is_empty() {
            ui.colored_label(egui::Color32::GRAY, "No hay archivos exportados aún. Realiza una búsqueda y pulsa 'Exportar a BibTeX' o 'Exportar a CSV'.");
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
                        let badge = if exp.format == "bib" || exp.format == "bibtex" { "📚 BIB" } else { "📊 CSV" };
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
