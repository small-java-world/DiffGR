#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use diffgr_gui::app::{install_japanese_font_fallbacks, DiffgrGuiApp, StartupArgs};
use eframe::egui;

fn main() -> eframe::Result {
    let args = StartupArgs::from_env();
    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_app_id("diffgr-rust-gui")
            .with_title("DiffGR Review")
            .with_inner_size([1500.0, 940.0])
            .with_min_inner_size([1040.0, 720.0]),
        centered: true,
        persist_window: true,
        ..Default::default()
    };

    eframe::run_native(
        "DiffGR Review",
        native_options,
        Box::new(move |cc| {
            install_japanese_font_fallbacks(&cc.egui_ctx);
            Ok(Box::new(DiffgrGuiApp::new(args.clone(), cc)))
        }),
    )
}
