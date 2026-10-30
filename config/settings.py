"""
Configuration module for MCPCONECCT.
Manages environment variables, proxy configurations (Burp Suite),
timeouts, and session storage paths.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
EXPORTS_DIR = BASE_DIR / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env if present
load_dotenv(BASE_DIR / ".env")

# Burp Suite / Proxy Settings
BURP_PROXY_ENABLED = os.getenv("BURP_PROXY_ENABLED", "false").lower() in ("true", "1", "yes")
BURP_PROXY_URL = os.getenv("BURP_PROXY_URL", "http://127.0.0.1:8080")
BURP_CA_BUNDLE = os.getenv("BURP_CA_BUNDLE", None)
DISABLE_SSL_VERIFY = os.getenv("DISABLE_SSL_VERIFY", "true").lower() in ("true", "1", "yes")

# HTTP Timeout (seconds)
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30.0"))

# User-Agent for requests mimicking academic browser navigation
DEFAULT_USER_AGENT = os.getenv(
    "DEFAULT_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Persistent Auth Store
AUTH_STORE_FILE = CONFIG_DIR / "auth_store.json"
SYNTAX_RULES_FILE = CONFIG_DIR / "syntax_rules.json"

# Supported Databases
SUPPORTED_DATABASES = ["scopus", "ieee", "wos", "springer"]


def get_platform_config(platform: str) -> dict:
    """Loads configuration for a given platform from auth_store.json."""
    import json
    if AUTH_STORE_FILE.exists():
        try:
            with open(AUTH_STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(platform.lower(), {})
        except Exception:
            pass
    return {}


def get_base_url(platform: str, default: str) -> str:
    """
    Returns the effective base URL for a platform, respecting base_url_override
    for EZProxy or OpenAthens university environments.
    """
    cfg = get_platform_config(platform)
    override = cfg.get("base_url_override")
    if override and isinstance(override, str) and override.strip():
        return override.strip().rstrip("/")
    return default.rstrip("/")

