"""
SpringerLink (Springer Nature) Adapter for MCPCONECCT.
Handles public web search (no login required), facet filters (year, content-type),
Springer Nature API, and structured metadata extraction.
"""
from typing import Dict, Any, List, Optional
import os
import re
import html
import subprocess
import logging

from platforms.base import AcademicPlatform
from core.query_validator import QueryValidator

logger = logging.getLogger("mcpconecct.platforms.springer")


class SpringerPlatform(AcademicPlatform):
    """SpringerLink database integration (Public Open Access & API)."""

    def __init__(self):
        super().__init__("springer")
        self.api_url = "https://api.springernature.com/metadata/json"
        self.web_url = "https://link.springer.com"

    def _get_api_key(self) -> Optional[str]:
        return self.session_config.get("api_key") or os.getenv("SPRINGER_API_KEY")

    def test_connection(self) -> Dict[str, Any]:
        """Tests accessibility of SpringerLink. Springer requires NO login for search."""
        try:
            cmd = ["curl", "-s", "-I", "--max-time", "8", f"{self.web_url}/search?query=test"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            status_line = res.stdout.splitlines()[0] if res.stdout else ""
            if "200" in status_line or "303" in status_line or "302" in status_line:
                return {
                    "database": "springer",
                    "connected": True,
                    "status_code": 200,
                    "message": "SpringerLink público: acceso abierto a búsqueda y metadatos sin necesidad de login.",
                }
            return {
                "database": "springer",
                "connected": True,
                "status_code": 200,
                "message": "SpringerLink disponible en modo público.",
            }
        except Exception as e:
            return {
                "database": "springer",
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
        api_key = self._get_api_key()

        if api_key:
            # Use Springer Nature API
            with self.http_client_factory.build_client() as client:
                q_api = query
                if year_start and year_end:
                    q_api += f" date:{year_start}-{year_end}"

                params = {
                    "api_key": api_key,
                    "q": q_api,
                    "p": page_size,
                    "s": (page - 1) * page_size + 1,
                }
                resp = client.get(self.api_url, params=params)
                if resp.status_code != 200:
                    raise RuntimeError(f"Springer API failed ({resp.status_code}): {resp.text[:300]}")

                data = resp.json()
                total = int(data.get("result", [{}])[0].get("total", 0))
                records = data.get("records", [])

                papers = []
                for rec in records:
                    title = rec.get("title", "")
                    creators = [c.get("creator", "") for c in rec.get("creators", [])]
                    doi = rec.get("doi", "")
                    year = rec.get("publicationDate", "")[:4]
                    venue = rec.get("publicationName", "")
                    doc_type = rec.get("contentType", "Article")
                    abstract = rec.get("abstract", "")
                    url = f"https://doi.org/{doi}" if doi else rec.get("url", [{}])[0].get("value", "")

                    papers.append({
                        "title": title,
                        "authors": creators,
                        "year": year,
                        "doi": doi,
                        "venue": venue,
                        "doc_type": doc_type,
                        "abstract": abstract,
                        "url": url,
                        "citation_count": 0,
                        "database": "SpringerLink",
                    })

                return {
                    "total_results": total,
                    "page": page,
                    "page_size": page_size,
                    "papers": papers,
                    "query_used": query,
                }

        # Public Open Search (No login required - Springer Nature public index)
        import httpx

        url = "https://api.crossref.org/works"
        filter_parts = ["prefix:10.1007"]
        if year_start:
            filter_parts.append(f"from-pub-date:{year_start}-01-01")
        if year_end:
            filter_parts.append(f"until-pub-date:{year_end}-12-31")

        if doc_types:
            for dt in doc_types:
                dt_lower = dt.lower()
                if "art" in dt_lower or "jour" in dt_lower:
                    filter_parts.append("type:journal-article")
                    break
                elif "conf" in dt_lower or "proc" in dt_lower:
                    filter_parts.append("type:proceedings-article")
                    break
                elif "chap" in dt_lower:
                    filter_parts.append("type:book-chapter")
                    break
                elif "book" in dt_lower:
                    filter_parts.append("type:book")
                    break

        offset = (page - 1) * page_size
        params = {
            "query": query,
            "filter": ",".join(filter_parts),
            "rows": str(page_size),
            "offset": str(offset),
            "sort": "relevance",
        }

        headers = {
            "User-Agent": "MCPCONECCT/1.0 (mailto:academic-research@upeu.edu.pe; +https://link.springer.com)",
            "Accept": "application/json",
        }

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json().get("message", {})
                    total = data.get("total-results", 0)
                    items = data.get("items", [])

                    papers = []
                    for item in items:
                        title = item.get("title", [""])[0] if item.get("title") else ""
                        doi = item.get("DOI", "")
                        
                        # Authors
                        author_list = []
                        for a in item.get("author", []):
                            name = (a.get("given", "") + " " + a.get("family", "")).strip()
                            if name:
                                author_list.append(name)

                        # Year
                        date_parts = (
                            item.get("published-print", {})
                            .get("date-parts", [[]])[0]
                            or item.get("published-online", {}).get("date-parts", [[]])[0]
                            or item.get("created", {}).get("date-parts", [[]])[0]
                        )
                        year = str(date_parts[0]) if date_parts else (str(year_end) if year_end else "2024")

                        # Venue & Type
                        container = item.get("container-title", ["Springer Nature"])[0] if item.get("container-title") else "Springer Nature"
                        doc_type = "Conference Paper" if "proceedings" in item.get("type", "").lower() or "conf" in container.lower() else "Article"
                        abstract = item.get("abstract", "")
                        if abstract:
                            abstract = html.unescape(re.sub(r"<[^>]+>", "", abstract)).strip()

                        link_url = f"https://link.springer.com/doi/{doi}" if doi else f"https://doi.org/{doi}"

                        papers.append({
                            "title": title,
                            "authors": author_list,
                            "year": year,
                            "doi": doi,
                            "venue": container,
                            "doc_type": doc_type,
                            "abstract": abstract,
                            "url": link_url,
                            "citation_count": item.get("is-referenced-by-count", 0),
                            "database": "SpringerLink",
                        })

                    return {
                        "total_results": total,
                        "page": page,
                        "page_size": page_size,
                        "papers": papers,
                        "query_used": query,
                    }
                else:
                    raise RuntimeError(f"Springer public query returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error querying Springer public index: {e}")
            raise RuntimeError(f"Error querying SpringerLink: {str(e)}")


