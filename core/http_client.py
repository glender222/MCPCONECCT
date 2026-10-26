"""
HTTP Client for MCPCONECCT.
Provides HTTP session management, proxy routing through Burp Suite,
SSL verification toggles, persistent cookie handling, and cURL parsing.
"""
from typing import Dict, Any, Optional, Tuple
import json
import logging
import re
import shlex
import httpx

from config import settings

logger = logging.getLogger("mcpconecct.http_client")


class SessionStore:
    """Manages persistent session storage in auth_store.json."""

    @staticmethod
    def load_store() -> Dict[str, Any]:
        if settings.AUTH_STORE_FILE.exists():
            try:
                with open(settings.AUTH_STORE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read auth_store.json: {e}")
        return {}

    @staticmethod
    def save_store(data: Dict[str, Any]) -> None:
        try:
            with open(settings.AUTH_STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write auth_store.json: {e}")

    @classmethod
    def get_session(cls, database: str) -> Dict[str, Any]:
        store = cls.load_store()
        return store.get(database.lower(), {})

    @classmethod
    def update_session(
        cls,
        database: str,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        store = cls.load_store()
        db_key = database.lower()
        if db_key not in store:
            store[db_key] = {"enabled": True, "cookies": {}, "headers": {}}

        if cookies is not None:
            store[db_key]["cookies"] = {**store[db_key].get("cookies", {}), **cookies}
        if headers is not None:
            store[db_key]["headers"] = {**store[db_key].get("headers", {}), **headers}
        if api_key is not None:
            store[db_key]["api_key"] = api_key
        if status is not None:
            store[db_key]["status"] = status

        cls.save_store(store)
        return store[db_key]


def parse_curl_command(curl_command: str) -> Dict[str, Any]:
    """
    Parses a standard cURL command (e.g. copied from Burp Suite or DevTools)
    and extracts the URL, headers, and cookies.
    """
    cleaned = curl_command.strip()
    if cleaned.startswith("$"):
        cleaned = cleaned[1:].strip()

    # Split using shlex to respect quotes and escapes
    try:
        tokens = shlex.split(cleaned)
    except Exception as e:
        # Fallback to simple split if shlex fails on multiline escapes
        tokens = cleaned.replace("\\\n", " ").replace("\\\r\n", " ").split()

    url = ""
    headers: Dict[str, str] = {}
    cookies: Dict[str, str] = {}
    method = "GET"
    data = None

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token in ("-H", "--header") and i + 1 < len(tokens):
            header_val = tokens[i + 1]
            if ":" in header_val:
                k, v = header_val.split(":", 1)
                k_clean = k.strip()
                v_clean = v.strip()
                if k_clean.lower() == "cookie":
                    # Parse Cookie header
                    for pair in v_clean.split(";"):
                        if "=" in pair:
                            ck, cv = pair.strip().split("=", 1)
                            cookies[ck.strip()] = cv.strip()
                else:
                    headers[k_clean] = v_clean
            i += 1
        elif token in ("-b", "--cookie") and i + 1 < len(tokens):
            cookie_val = tokens[i + 1]
            for pair in cookie_val.split(";"):
                if "=" in pair:
                    ck, cv = pair.strip().split("=", 1)
                    cookies[ck.strip()] = cv.strip()
            i += 1
        elif token in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 1
        elif token in ("-d", "--data", "--data-raw") and i + 1 < len(tokens):
            data = tokens[i + 1]
            if method == "GET":
                method = "POST"
            i += 1
        elif token.startswith("http://") or token.startswith("https://"):
            url = token
        elif token == "curl":
            pass
        i += 1

    return {
        "url": url,
        "method": method,
        "headers": headers,
        "cookies": cookies,
        "data": data,
    }


class AcademicHttpClient:
    """HTTP client configured for academic databases with Burp Suite support."""

    def __init__(self, database: str):
        self.database = database.lower()
        self.session_config = SessionStore.get_session(self.database)

    def _get_proxy_url(self) -> Optional[str]:
        if settings.BURP_PROXY_ENABLED:
            return settings.BURP_PROXY_URL
        return None

    def _get_verify_option(self) -> Any:
        if settings.BURP_PROXY_ENABLED and settings.DISABLE_SSL_VERIFY:
            return False
        if settings.BURP_CA_BUNDLE:
            return settings.BURP_CA_BUNDLE
        return True

    def build_client(self) -> httpx.Client:
        """Creates an httpx.Client with configured proxy, cookies, and headers."""
        headers = {
            "User-Agent": settings.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        custom_headers = self.session_config.get("headers", {})
        headers.update(custom_headers)

        cookies = self.session_config.get("cookies", {})
        proxy = self._get_proxy_url()
        verify = self._get_verify_option()

        return httpx.Client(
            headers=headers,
            cookies=cookies,
            proxy=proxy,
            verify=verify,
            timeout=settings.HTTP_TIMEOUT,
            follow_redirects=True,
        )

    def build_async_client(self) -> httpx.AsyncClient:
        """Creates an async httpx.AsyncClient."""
        headers = {
            "User-Agent": settings.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        custom_headers = self.session_config.get("headers", {})
        headers.update(custom_headers)

        cookies = self.session_config.get("cookies", {})
        proxy = self._get_proxy_url()
        verify = self._get_verify_option()

        return httpx.AsyncClient(
            headers=headers,
            cookies=cookies,
            proxy=proxy,
            verify=verify,
            timeout=settings.HTTP_TIMEOUT,
            follow_redirects=True,
        )
