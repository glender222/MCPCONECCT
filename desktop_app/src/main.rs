mod app;
mod burp_launcher;
mod db_client;
mod firefox_extractor;
mod pico_translator;

use app::McpDesktopApp;

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([1150.0, 750.0])
            .with_min_inner_size([900.0, 600.0])
            .with_title("MCPCONECCT · Core Academic Desktop Hub"),
        ..Default::default()
    };

    eframe::run_native(
        "MCPCONECCT",
        options,
        Box::new(|_cc| Ok(Box::new(McpDesktopApp::default()))),
    )
}
