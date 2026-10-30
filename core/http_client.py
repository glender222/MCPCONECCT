"""
HTTP Client for MCPCONECCT.
Provides HTTP session management, proxy routing through Burp Suite,
SSL verification toggles, persistent cookie handling, and cURL parsing.
"""
from typing import Dict, Any, Optional, Tuple
from enum import Enum
import json
import logging
import re
import shlex
import urllib.parse
import httpx

from config import settings

logger = logging.getLogger("mcpconecct.http_client")


class SessionHealthStatus(str, Enum):
    """Health diagnostic statuses for academic platform sessions."""
    VALID_INSTITUTIONAL = "VALID_INSTITUTIONAL"
    VALID_PUBLIC = "VALID_PUBLIC"
    WAF_CHALLENGE = "WAF_CHALLENGE"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    NETWORK_ERROR = "NETWORK_ERROR"


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
        base_url_override: Optional[str] = None,
        auth_mode: Optional[str] = None,
        inst_token: Optional[str] = None,
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
        if base_url_override is not None:
            store[db_key]["base_url_override"] = base_url_override
        if auth_mode is not None:
            store[db_key]["auth_mode"] = auth_mode
        if inst_token is not None:
            store[db_key]["inst_token"] = inst_token

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

    base_url_override = None
    if url:
        parsed_url = urllib.parse.urlparse(url)
        netloc = parsed_url.netloc.lower()
        if "ezproxy" in netloc or "openathens" in netloc or "libproxy" in netloc:
            base_url_override = f"{parsed_url.scheme}://{parsed_url.netloc}"

    return {
        "url": url,
        "base_url_override": base_url_override,
        "method": method,
        "headers": headers,
        "cookies": cookies,
        "data": data,
    }


def diagnose_platform_session(database: str) -> Dict[str, Any]:
    """
    Performs a lightweight HTTP probe to verify session health and detect WAF challenges,
    institutional logins, or expired sessions.
    """
    db = database.lower().strip()
    urls = {
        "ieee": settings.get_base_url("ieee", "https://ieeexplore.ieee.org") + "/Xplore/home.jsp",
        "scopus": settings.get_base_url("scopus", "https://www.scopus.com") + "/search/form.uri?display=basic",
        "springer": settings.get_base_url("springer", "https://link.springer.com") + "/",
        "wos": settings.get_base_url("wos", "https://www.webofscience.com") + "/wos/woscc/basic-search",
    }
    target_url = urls.get(db)
    if not target_url:
        return {
            "database": db,
            "status": SessionHealthStatus.NETWORK_ERROR.value,
            "status_code": 0,
            "detail": f"Unsupported platform '{database}'",
        }

    client_wrapper = AcademicHttpClient(db)
    try:
        with client_wrapper.build_client() as client:
            resp = client.get(target_url, timeout=12.0)
            status_code = resp.status_code
            body_text = resp.text.lower()
            resp_url = str(resp.url).lower()

            # 1. Detect WAF / Cloudflare / Bot Challenges
            waf_indicators = [
                "cloudflare", "cf-ray", "challenge-running", "turnstile",
                "please verify you are a human", "perimeterx", "datadome",
                "incapsula", "access denied", "attention required! | cloudflare"
            ]
            if status_code in (403, 429) or any(w in body_text for w in waf_indicators):
                status = SessionHealthStatus.WAF_CHALLENGE
                detail = f"WAF / Bot challenge detected (HTTP {status_code})"

            # 2. Detect Session Expired or Redirect to Login
            elif (
                "id.elsevier.com" in resp_url or
                "login.microsoftonline.com" in resp_url or
                "shibboleth" in resp_url or
                "cas/login" in resp_url or
                ("login" in resp_url and "search" not in resp_url) or
                "session expired" in body_text or
                "your session has timed out" in body_text
            ):
                status = SessionHealthStatus.SESSION_EXPIRED
                detail = f"Session expired or redirected to login: {resp.url}"

            # 3. Check for Institutional Access markers
            elif db == "ieee":
                if any(x in body_text for x in ["instname", "isinstitutional", "institutional sign in", "logged in as", "university"]):
                    status = SessionHealthStatus.VALID_INSTITUTIONAL
                    detail = "Active institutional session verified on IEEE Xplore"
                elif status_code == 200:
                    status = SessionHealthStatus.VALID_PUBLIC
                    detail = "IEEE Xplore reachable in public mode"
                else:
                    status = SessionHealthStatus.NETWORK_ERROR
                    detail = f"Unexpected status code HTTP {status_code}"

            elif db == "scopus":
                if any(x in body_text for x in ["orgname", "institution", "elsevier_institution"]):
                    status = SessionHealthStatus.VALID_INSTITUTIONAL
                    detail = "Active institutional access confirmed on Scopus"
                elif status_code == 200:
                    status = SessionHealthStatus.VALID_PUBLIC
                    detail = "Scopus search portal reachable"
                else:
                    status = SessionHealthStatus.NETWORK_ERROR
                    detail = f"Unexpected status code HTTP {status_code}"

            elif db == "springer":
                if any(x in body_text for x in ["access provided by", "provided by", "institutional access"]):
                    status = SessionHealthStatus.VALID_INSTITUTIONAL
                    detail = "Institutional access verified on SpringerLink"
                elif status_code == 200:
                    status = SessionHealthStatus.VALID_PUBLIC
                    detail = "SpringerLink reachable"
                else:
                    status = SessionHealthStatus.NETWORK_ERROR
                    detail = f"Unexpected status code HTTP {status_code}"

            elif db == "wos":
                if "clarivate" in body_text and status_code == 200:
                    status = SessionHealthStatus.VALID_INSTITUTIONAL
                    detail = "Web of Science reachable"
                else:
                    status = SessionHealthStatus.VALID_PUBLIC
                    detail = f"Web of Science HTTP {status_code}"
            else:
                status = SessionHealthStatus.VALID_PUBLIC
                detail = f"HTTP {status_code}"

            SessionStore.update_session(db, status=status.value)
            return {
                "database": db,
                "status": status.value,
                "status_code": status_code,
                "detail": detail,
                "final_url": str(resp.url),
            }

    except httpx.RequestError as exc:
        err_msg = f"Network connection error: {str(exc)}"
        SessionStore.update_session(db, status=SessionHealthStatus.NETWORK_ERROR.value)
        return {
            "database": db,
            "status": SessionHealthStatus.NETWORK_ERROR.value,
            "status_code": 0,
            "detail": err_msg,
        }
    except Exception as exc:
        err_msg = f"Diagnostic probe failed: {str(exc)}"
        return {
            "database": db,
            "status": SessionHealthStatus.NETWORK_ERROR.value,
            "status_code": 0,
            "detail": err_msg,
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
