"""
Scopus (Elsevier) Adapter for MCPCONECCT.
Handles query formatting, Elsevier API / Web session searching,
filtering by year/doctype, and result normalization.
"""
from typing import Dict, Any, List, Optional
import os
import logging
import httpx

from platforms.base import AcademicPlatform
from core.query_validator import QueryValidator

logger = logging.getLogger("mcpconecct.platforms.scopus")


class ScopusPlatform(AcademicPlatform):
    """Scopus academic database integration."""

    def __init__(self):
        super().__init__("scopus")
        self.api_url = "https://api.elsevier.com/content/search/scopus"
        self.web_url = "https://www.scopus.com"

    def _get_api_key(self) -> Optional[str]:
        return self.session_config.get("api_key") or os.getenv("ELSEVIER_API_KEY")

    def _get_inst_token(self) -> Optional[str]:
        return self.session_config.get("inst_token") or os.getenv("ELSEVIER_INST_TOKEN")

    def build_query(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
    ) -> str:
        final_query = query.strip()

        # Add year filter if specified
        if year_start and year_end:
            final_query += f" AND PUBYEAR > {year_start - 1} AND PUBYEAR < {year_end + 1}"
        elif year_start:
            final_query += f" AND PUBYEAR > {year_start - 1}"
        elif year_end:
            final_query += f" AND PUBYEAR < {year_end + 1}"

        # Add document type filter
        if doc_types:
            type_clauses = []
            for dt in doc_types:
                dt_lower = dt.lower()
                if "art" in dt_lower or dt_lower == "ar":
                    type_clauses.append('DOCTYPE(ar)')
                elif "conf" in dt_lower or "proc" in dt_lower or dt_lower == "cp":
                    type_clauses.append('DOCTYPE(cp)')
                elif "rev" in dt_lower or dt_lower == "re":
                    type_clauses.append('DOCTYPE(re)')
                elif "chap" in dt_lower or dt_lower == "ch":
                    type_clauses.append('DOCTYPE(ch)')
                elif "book" in dt_lower or dt_lower == "bk":
                    type_clauses.append('DOCTYPE(bk)')
                elif "survey" in dt_lower or dt_lower == "sh":
                    type_clauses.append('DOCTYPE(sh)')
                else:
                    type_clauses.append(f'DOCTYPE({dt_lower})')
            if type_clauses:
                final_query += " AND ( " + " OR ".join(type_clauses) + " )"

        return final_query

    def test_connection(self) -> Dict[str, Any]:
        api_key = self._get_api_key()
        cookies = self.session_config.get("cookies", {})

        if not api_key and not cookies:
            return {
                "database": "scopus",
                "connected": False,
                "status_code": None,
                "message": "Unconfigured: No Elsevier API Key or browser session cookies provided. Configure using 'configure_auth' or 'import_curl'.",
            }

        with self.http_client_factory.build_client() as client:
            try:
                if api_key:
                    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
                    inst_token = self._get_inst_token()
                    if inst_token:
                        headers["X-ELS-Insttoken"] = inst_token

                    resp = client.get(
                        self.api_url,
                        params={"query": "TITLE(test)", "count": "1"},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        return {
                            "database": "scopus",
                            "connected": True,
                            "status_code": 200,
                            "message": "Authentication successful via Elsevier API Key.",
                        }
                    return {
                        "database": "scopus",
                        "connected": False,
                        "status_code": resp.status_code,
                        "message": f"Elsevier API returned status {resp.status_code}: {resp.text[:200]}",
                    }
                else:
                    # Test via Scopus web portal session / gateway probe
                    headers = {
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json",
                        "x-source": "scopus-frontend",
                        "Referer": f"{self.web_url}/pages/search/publications?type=advanced",
                    }
                    probe_payload = {
                        "query": "TITLE(test)",
                        "documentClassification": "primary",
                        "resultSet": {"offset": 0, "itemCount": 1},
                    }
                    try:
                        resp = client.post(
                            f"{self.web_url}/gateway/documents/search",
                            json=probe_payload,
                            headers=headers,
                            timeout=10,
                        )
                        if resp.status_code == 200:
                            total = resp.json().get("metadata", {}).get("totalCount", 0)
                            return {
                                "database": "scopus",
                                "connected": True,
                                "status_code": 200,
                                "message": f"Sesión de Scopus activa y verificada (búsqueda funcional: {total:,} registros).",
                            }
                    except Exception:
                        pass

                    # Fallback test via web portal session
                    resp = client.get(f"{self.web_url}/pages/home", follow_redirects=False)
                    is_ok = resp.status_code in (200, 302, 303, 307) or resp.status_code < 400
                    return {
                        "database": "scopus",
                        "connected": is_ok,
                        "status_code": resp.status_code,
                        "message": f"Sesión de Scopus activa y accesible (código HTTP {resp.status_code})." if is_ok else f"Respuesta inesperada {resp.status_code}.",
                    }
            except Exception as e:
                return {
                    "database": "scopus",
                    "connected": False,
                    "status_code": None,
                    "message": f"Connection error: {str(e)}",
                }

    def get_paper_count(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
    ) -> int:
        result = self.search(query, year_start, year_end, doc_types, page=1, page_size=1)
        return result.get("total_results", 0)

    def search(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        compiled_query = self.build_query(query, year_start, year_end, doc_types)
        api_key = self._get_api_key()
        start = (page - 1) * page_size

        with self.http_client_factory.build_client() as client:
            if api_key:
                headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
                inst_token = self._get_inst_token()
                if inst_token:
                    headers["X-ELS-Insttoken"] = inst_token

                params = {
                    "query": compiled_query,
                    "count": str(page_size),
                    "start": str(start),
                    "view": "STANDARD",
                }
                resp = client.get(self.api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    raise RuntimeError(f"Scopus API request failed ({resp.status_code}): {resp.text[:300]}")

                data = resp.json().get("search-results", {})
                total_results = int(data.get("opensearch:totalResults", 0))

                papers = []
                for entry in data.get("entry", []):
                    title = entry.get("dc:title", "")
                    creator = entry.get("dc:creator", "")
                    doi = entry.get("prism:doi", "")
                    year = entry.get("prism:coverDate", "")[:4]
                    venue = entry.get("prism:publicationName", "")
                    doc_type = entry.get("subtypeDescription", "Article")
                    abstract = entry.get("dc:description", "")
                    citation_count = int(entry.get("citedby-count", 0))
                    url = ""
                    for link in entry.get("link", []):
                        if link.get("@ref") == "scopus":
                            url = link.get("@href", "")

                    papers.append({
                        "title": title,
                        "authors": [creator] if creator else [],
                        "year": year,
                        "doi": doi,
                        "venue": venue,
                        "doc_type": doc_type,
                        "abstract": abstract,
                        "url": url,
                        "citation_count": citation_count,
                        "database": "Scopus",
                    })

                return {
                    "total_results": total_results,
                    "page": page,
                    "page_size": page_size,
                    "papers": papers,
                    "query_used": compiled_query,
                }
            else:
                # Web session querying via Scopus SPA gateway
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "x-source": "scopus-frontend",
                    "Referer": f"{self.web_url}/pages/search/publications?type=advanced",
                }
                payload = {
                    "query": compiled_query,
                    "documentClassification": "primary",
                    "resultSet": {
                        "offset": start,
                        "itemCount": page_size,
                    },
                    "sort": [{"fieldName": "datesort", "order": "desc"}],
                }
                resp = client.post(
                    f"{self.web_url}/gateway/documents/search",
                    json=payload,
                    headers=headers,
                    timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    metadata = data.get("metadata", {})
                    total = metadata.get("totalCount", 0)
                    items = data.get("items", [])

                    DOCTYPE_NAMES = {
                        "ar": "Article",
                        "cp": "Conference Paper",
                        "re": "Review",
                        "bk": "Book",
                        "ch": "Book Chapter",
                        "sh": "Short Survey",
                        "no": "Note",
                        "ed": "Editorial",
                        "le": "Letter",
                        "er": "Erratum",
                        "cr": "Conference Review",
                    }

                    papers = []
                    for item in items:
                        authors = []
                        for a in item.get("authors", []):
                            pname = a.get("preferredName", {})
                            full = pname.get("full") or f"{pname.get('first', '')} {pname.get('last', '')}".strip()
                            if full:
                                authors.append(full)

                        abstract_texts = item.get("abstractText", [])
                        abstract = "\n\n".join(abstract_texts) if isinstance(abstract_texts, list) else str(abstract_texts or "")
                        eid = item.get("eid", "")
                        url = f"https://www.scopus.com/record/display.uri?eid={eid}&origin=resultslist" if eid else (f"https://doi.org/{item.get('doi')}" if item.get("doi") else "")
                        raw_dt = item.get("documentType", "ar")
                        doc_type_name = DOCTYPE_NAMES.get(raw_dt, raw_dt.capitalize() if raw_dt else "Article")

                        papers.append({
                            "title": item.get("title", ""),
                            "authors": authors,
                            "year": str(item.get("pubYear", "")),
                            "doi": item.get("doi", ""),
                            "venue": item.get("source", {}).get("title", ""),
                            "doc_type": doc_type_name,
                            "abstract": abstract,
                            "url": url,
                            "citation_count": item.get("citations", {}).get("count", 0),
                            "database": "Scopus",
                        })
                    return {
                        "total_results": total,
                        "page": page,
                        "page_size": page_size,
                        "papers": papers,
                        "query_used": compiled_query,
                    }
                else:
                    raise RuntimeError(
                        f"Scopus web session returned HTTP {resp.status_code}: {resp.text[:200]}. "
                        "Please update your session cookies using 'configure_auth' or 'import_curl'."
                    )
