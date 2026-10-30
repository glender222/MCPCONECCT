"""
Web of Science (Clarivate) Adapter for MCPCONECCT.
Handles Topic TS=(...) queries, session authentication,
Clarivate API / Web endpoint integration, and paper extraction.
"""
from typing import Dict, Any, List, Optional
import os
import logging

from platforms.base import AcademicPlatform, CanonicalPaper
from core.query_validator import QueryValidator

logger = logging.getLogger("mcpconecct.platforms.wos")


class WosPlatform(AcademicPlatform):
    """Web of Science (WoS) database integration."""

    def __init__(self):
        super().__init__("wos")
        self.starter_api_url = "https://api.clarivate.com/apis/wos-starter/v1/documents"
        self.web_url = self.get_base_url("https://www.webofscience.com")

    def _get_api_key(self) -> Optional[str]:
        return self.session_config.get("api_key") or os.getenv("WOS_STARTER_API_KEY")

    def build_query(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
    ) -> str:
        final_query = query.strip()
        if not final_query.startswith("TS="):
            final_query = f"TS=({final_query})"

        if year_start and year_end:
            final_query += f" AND PY=({year_start}-{year_end})"
        elif year_start:
            final_query += f" AND PY=({year_start}-2030)"
        elif year_end:
            final_query += f" AND PY=(1900-{year_end})"

        if doc_types:
            type_clauses = []
            for dt in doc_types:
                dt_lower = dt.lower()
                if "art" in dt_lower:
                    type_clauses.append('DT="Article"')
                elif "conf" in dt_lower or "proc" in dt_lower:
                    type_clauses.append('DT="Proceedings Paper"')
            if type_clauses:
                final_query += f" AND ({' OR '.join(type_clauses)})"

        return final_query

    def test_connection(self) -> Dict[str, Any]:
        api_key = self._get_api_key()
        cookies = self.session_config.get("cookies", {})

        if not api_key and not cookies:
            return {
                "database": "wos",
                "connected": False,
                "status_code": None,
                "message": "Unconfigured: No Web of Science API Key or browser session cookies provided.",
            }

        with self.http_client_factory.build_client() as client:
            try:
                if api_key:
                    headers = {"X-ApiKey": api_key, "Accept": "application/json"}
                    resp = client.get(self.starter_api_url, params={"q": "TS=(test)", "limit": 1}, headers=headers)
                    return {
                        "database": "wos",
                        "connected": resp.status_code == 200,
                        "status_code": resp.status_code,
                        "message": "Connected via Clarivate WoS Starter API." if resp.status_code == 200 else f"WoS API returned {resp.status_code}",
                    }
                else:
                    resp = client.get(f"{self.web_url}/wos/woscc/advanced-search")
                    return {
                        "database": "wos",
                        "connected": resp.status_code < 400,
                        "status_code": resp.status_code,
                        "message": f"WoS portal accessible with status {resp.status_code}.",
                    }
            except Exception as e:
                return {
                    "database": "wos",
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

        with self.http_client_factory.build_client() as client:
            if api_key:
                headers = {"X-ApiKey": api_key, "Accept": "application/json"}
                params = {
                    "q": compiled_query,
                    "limit": page_size,
                    "page": page,
                }
                resp = client.get(self.starter_api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    raise RuntimeError(f"WoS API failed ({resp.status_code}): {resp.text[:300]}")

                data = resp.json()
                metadata = data.get("metadata", {})
                total = metadata.get("total", 0)
                hits = data.get("hits", [])

                papers = []
                for hit in hits:
                    title = hit.get("title", "")
                    names = hit.get("names", {})
                    authors = [a.get("displayName", "") for a in names.get("authors", []) if a.get("displayName")]
                    source = hit.get("source", {})
                    venue = source.get("sourceTitle", "")
                    year = str(source.get("publishYear", ""))
                    identifiers = hit.get("identifiers", {})
                    doi = identifiers.get("doi", "")
                    doc_types_list = hit.get("types", ["Article"])
                    doc_type = doc_types_list[0] if doc_types_list else "Article"
                    links = hit.get("links", {})
                    record_url = links.get("record", "")

                    parsed_year = None
                    if year:
                        try:
                            parsed_year = int(str(year).strip())
                        except Exception:
                            parsed_year = None

                    paper = CanonicalPaper(
                        title=title,
                        authors=authors,
                        year=parsed_year,
                        doi=doi,
                        venue=venue,
                        doc_type=doc_type,
                        abstract="",
                        url=record_url,
                        sources=["wos"],
                        citation_count=0,
                    ).finalize()
                    papers.append(paper.to_dict())

                return {
                    "total_results": total,
                    "page": page,
                    "page_size": page_size,
                    "papers": papers,
                    "query_used": compiled_query,
                }
            else:
                # Web session querying
                headers = {"Accept": "application/json, text/plain, */*"}
                params = {
                    "q": compiled_query,
                    "page": page,
                    "limit": page_size,
                }
                resp = client.get(f"{self.web_url}/api/wosnx/indic/search/advanced", params=params, headers=headers)
                if resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
                    data = resp.json()
                    total = data.get("totalHits", 0)
                    records = data.get("records", [])
                    papers = []
                    for rec in records:
                        raw_year = rec.get("year", "")
                        parsed_year = None
                        if raw_year:
                            try:
                                parsed_year = int(str(raw_year).strip())
                            except Exception:
                                parsed_year = None

                        paper = CanonicalPaper(
                            title=rec.get("title", ""),
                            authors=rec.get("authors", []),
                            year=parsed_year,
                            doi=rec.get("doi", ""),
                            venue=rec.get("journal", ""),
                            doc_type=rec.get("docType", "Article"),
                            abstract=rec.get("abstract", "") or "",
                            url=rec.get("url", ""),
                            sources=["wos"],
                            citation_count=rec.get("citations", 0),
                        ).finalize()
                        papers.append(paper.to_dict())
                    return {
                        "total_results": total,
                        "page": page,
                        "page_size": page_size,
                        "papers": papers,
                        "query_used": compiled_query,
                    }
                else:
                    raise RuntimeError(
                        f"WoS web request returned HTTP {resp.status_code}. "
                        "Please update your session cookies using 'configure_auth' or 'import_curl'."
                    )
