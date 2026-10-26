"""
Authentication and Burp Suite management MCP tools.
"""
from typing import Dict, Any, Optional
import os
from config import settings
from core.http_client import SessionStore, parse_curl_command
from platforms import get_platform, PLATFORMS


def configure_auth(
    database: str,
    cookies: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Configures session cookies, custom headers, or API keys for an academic platform.
    Settings are saved persistently in config/auth_store.json.

    Args:
        database: Target platform ('scopus', 'ieee', 'wos', 'springer').
        cookies: Optional key-value dictionary of session cookies.
        headers: Optional dictionary of HTTP headers (User-Agent, Authorization, etc.).
        api_key: Optional API key.
    """
    db = database.lower().strip()
    updated = SessionStore.update_session(
        database=db,
        cookies=cookies,
        headers=headers,
        api_key=api_key,
        status="configured"
    )
    return {
        "status": "success",
        "database": db,
        "cookies_count": len(updated.get("cookies", {})),
        "headers_count": len(updated.get("headers", {})),
        "has_api_key": bool(updated.get("api_key")),
    }


def import_curl(database: str, curl_command: str) -> Dict[str, Any]:
    """
    Imports an authenticated session directly from a cURL command.
    You can right-click any request in Burp Suite (or browser DevTools) -> 'Copy as cURL',
    and pass it here. The MCP server automatically parses and stores cookies, headers, and tokens.

    Args:
        database: Target database ('scopus', 'ieee', 'wos', 'springer').
        curl_command: The cURL command string copied from Burp Suite.
    """
    db = database.lower().strip()
    parsed = parse_curl_command(curl_command)

    updated = SessionStore.update_session(
        database=db,
        cookies=parsed.get("cookies"),
        headers=parsed.get("headers"),
        status="configured"
    )

    return {
        "status": "success",
        "database": db,
        "target_url": parsed.get("url"),
        "cookies_imported": list(parsed.get("cookies", {}).keys()),
        "headers_imported": list(parsed.get("headers", {}).keys()),
        "message": f"Successfully imported session for {db} from cURL.",
    }


def configure_burp_proxy(
    enabled: bool = True,
    proxy_url: str = "http://127.0.0.1:8080",
    disable_ssl_verification: bool = True,
) -> Dict[str, Any]:
    """
    Enables or disables routing MCP server HTTP requests through Burp Suite.
    When enabled, all searches, session tests, and exports will appear in Burp Suite's
    HTTP History and Repeater for inspection and manual request tweaking.

    Args:
        enabled: Set to True to route through Burp Suite, False for direct connection.
        proxy_url: Upstream proxy URL (defaults to http://127.0.0.1:8080).
        disable_ssl_verification: Set to True to allow Burp Suite's self-signed CA.
    """
    settings.BURP_PROXY_ENABLED = enabled
    settings.BURP_PROXY_URL = proxy_url
    settings.DISABLE_SSL_VERIFY = disable_ssl_verification

    # Update environment variables for the current process
    os.environ["BURP_PROXY_ENABLED"] = str(enabled).lower()
    os.environ["BURP_PROXY_URL"] = proxy_url
    os.environ["DISABLE_SSL_VERIFY"] = str(disable_ssl_verification).lower()

    return {
        "status": "success",
        "burp_proxy_enabled": settings.BURP_PROXY_ENABLED,
        "proxy_url": settings.BURP_PROXY_URL,
        "ssl_verification_disabled": settings.DISABLE_SSL_VERIFY,
        "message": f"Burp Suite proxy {'ENABLED' if enabled else 'DISABLED'} on {proxy_url}.",
    }


def test_connection(database: str) -> Dict[str, Any]:
    """
    Tests whether the current session, cookies, or API keys for a database are active and valid.

    Args:
        database: Target platform ('scopus', 'ieee', 'wos', 'springer').
    """
    platform = get_platform(database)
    result = platform.test_connection()
    result["burp_proxy_active"] = settings.BURP_PROXY_ENABLED
    return result


def get_database_status() -> Dict[str, Any]:
    """
    Returns the overall status of all 4 supported databases, current session storage,
    Burp Suite proxy configuration, and export directory.
    """
    store = SessionStore.load_store()
    databases_info = {}

    for db_name, adapter in PLATFORMS.items():
        session_data = store.get(db_name, {})
        databases_info[db_name] = {
            "status": session_data.get("status", "unconfigured"),
            "cookies_count": len(session_data.get("cookies", {})),
            "has_api_key": bool(session_data.get("api_key") or getattr(adapter, "_get_api_key", lambda: None)()),
            "headers": list(session_data.get("headers", {}).keys()),
        }

    return {
        "burp_proxy_enabled": settings.BURP_PROXY_ENABLED,
        "burp_proxy_url": settings.BURP_PROXY_URL,
        "exports_directory": str(settings.EXPORTS_DIR),
        "databases": databases_info,
    }


def register_auth_tools(mcp) -> None:
    mcp.tool()(configure_auth)
    mcp.tool()(import_curl)
    mcp.tool()(configure_burp_proxy)
    mcp.tool()(test_connection)
    mcp.tool()(get_database_status)
