use std::net::TcpStream;
use std::path::Path;
use std::process::Command;
use std::time::Duration;

pub fn is_burp_proxy_running() -> bool {
    TcpStream::connect_timeout(
        &"127.0.0.1:8080".parse().unwrap(),
        Duration::from_millis(500),
    ).is_ok()
}

pub fn get_browser_executable() -> Option<String> {
    let burp_chrome = "/home/glender/BurpSuite/burpbrowser/154.0.8037.97/chrome";
    if Path::new(burp_chrome).exists() {
        return Some(burp_chrome.to_string());
    }
    if Path::new("/usr/bin/chromium").exists() {
        return Some("/usr/bin/chromium".to_string());
    }
    if Path::new("/usr/bin/google-chrome").exists() {
        return Some("/usr/bin/google-chrome".to_string());
    }
    None
}

pub fn launch_browser_for_platform(database: &str) -> Result<String, String> {
    let browser = get_browser_executable()
        .ok_or_else(|| "No se encontró ningún ejecutable de Chromium en el sistema.".to_string())?;

    let target_url = match database.to_lowercase().as_str() {
        "scopus" => "https://www.scopus.com/home.uri",
        "ieee" => "https://ieeexplore.ieee.org/search/advanced",
        "springer" => "https://link.springer.com",
        "wos" => "https://www.webofscience.com",
        _ => "https://google.com",
    };

    let child = Command::new(&browser)
        .arg("--proxy-server=http://127.0.0.1:8080")
        .arg("--remote-debugging-port=9222")
        .arg("--ignore-certificate-errors")
        .arg(format!("--user-data-dir=/tmp/mcp_chrome_{}", database))
        .arg(target_url)
        .spawn();

    match child {
        Ok(_) => Ok(format!("Navegador lanzado hacia {} enrutado por Burp Suite (127.0.0.1:8080).", target_url)),
        Err(e) => Err(format!("Error al lanzar navegador: {}", e)),
    }
}
