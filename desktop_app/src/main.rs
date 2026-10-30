mod app;
mod burp_launcher;
mod db_client;
mod firefox_extractor;
mod pico_translator;
mod research_client;

use app::McpDesktopApp;

fn setup_fonts(ctx: &eframe::egui::Context) {
    let mut fonts = eframe::egui::FontDefinitions::default();
    if let Ok(bytes) = std::fs::read("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") {
        fonts.font_data.insert(
            "dejavu_sans".to_owned(),
            std::sync::Arc::new(eframe::egui::FontData::from_owned(bytes)),
        );
        if let Some(family) = fonts.families.get_mut(&eframe::egui::FontFamily::Proportional) {
            family.insert(0, "dejavu_sans".to_owned());
        }
    }
    ctx.set_fonts(fonts);
}

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([1400.0, 900.0])
            .with_min_inner_size([980.0, 650.0])
            .with_title("MCPCONECCT · Core Academic Desktop Hub"),
        ..Default::default()
    };

    eframe::run_native(
        "MCPCONECCT",
        options,
        Box::new(|cc| {
            setup_fonts(&cc.egui_ctx);
            Ok(Box::new(McpDesktopApp::default()))
        }),
    )
}
