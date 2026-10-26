"""
IEEE Xplore Adapter for MCPCONECCT.
Handles IEEE Command Search, max 10 wildcard validation,
REST endpoint / API integration, and paper extraction.
"""
from typing import Dict, Any, List, Optional
import os
import logging

from platforms.base import AcademicPlatform
from core.query_validator import QueryValidator

logger = logging.getLogger("mcpconecct.platforms.ieee")


class IeeePlatform(AcademicPlatform):
    """IEEE Xplore database integration."""

    def __init__(self):
        super().__init__("ieee")
        self.rest_search_url = "https://ieeexplore.ieee.org/rest/search"
        self.api_url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

    def _get_api_key(self) -> Optional[str]:
        return self.session_config.get("api_key") or os.getenv("IEEE_API_KEY")

    def test_connection(self) -> Dict[str, Any]:
        with self.http_client_factory.build_client() as client:
            try:
                resp = client.get("https://ieeexplore.ieee.org/Xplore/home.jsp")
                return {
                    "database": "ieee",
                    "connected": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "message": f"IEEE Xplore portal accessible with status {resp.status_code}.",
                }
            except Exception as e:
                return {
                    "database": "ieee",
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
        # Validate wildcard count before making request
        val = QueryValidator.validate("ieee", query)
        if not val.is_valid:
            raise ValueError(f"Invalid IEEE query: {'; '.join(val.errors)}")

        payload: Dict[str, Any] = {
            "queryText": query,
            "pageNumber": page,
            "rowsPerPage": page_size,
        }

        # Apply year filter
        if year_start and year_end:
            payload["ranges"] = [f"{year_start}_{year_end}_Year"]

        # Apply document type filter using IEEE native refinements
        if doc_types:
            refinements = []
            for dt in doc_types:
                dt_lower = dt.lower()
                if "conf" in dt_lower:
                    refinements.append("ContentType:Conferences")
                elif "jour" in dt_lower or "art" in dt_lower or "period" in dt_lower:
                    refinements.append("ContentType:Journals")
                    refinements.append("ContentType:Magazines")
                elif "book" in dt_lower or "ebook" in dt_lower:
                    refinements.append("ContentType:Books")
                elif "standard" in dt_lower or "norm" in dt_lower:
                    refinements.append("ContentType:Standards")
                elif "early" in dt_lower:
                    refinements.append("ContentType:Early Access Articles")
                elif "course" in dt_lower:
                    refinements.append("ContentType:Courses")
            if refinements:
                payload["refinements"] = list(dict.fromkeys(refinements))

        with self.http_client_factory.build_client() as client:
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Referer": "https://ieeexplore.ieee.org/search/advanced/command",
            }

            resp = client.post(self.rest_search_url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"IEEE Xplore search failed (HTTP {resp.status_code}): {resp.text[:300]}. "
                    "Ensure your session cookies are updated using 'configure_auth' or 'import_curl'."
                )

            data = resp.json()
            total_records = data.get("totalRecords", 0)
            records = data.get("records", [])

            papers = []
            for rec in records:
                doc_type = rec.get("contentType", "Article")

                authors = [a.get("preferredName", "") for a in rec.get("authors", []) if a.get("preferredName")]
                title = rec.get("articleTitle", "") or rec.get("title", "")
                doi = rec.get("doi", "")
                year = str(rec.get("publicationYear", ""))
                venue = rec.get("publicationTitle", "")
                abstract = rec.get("abstract", "")
                url = f"https://ieeexplore.ieee.org{rec.get('documentLink', '')}"
                citation_count = rec.get("citationCount", 0)

                papers.append({
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": doi,
                    "venue": venue,
                    "doc_type": doc_type,
                    "abstract": abstract,
                    "url": url,
                    "citation_count": citation_count,
                    "database": "IEEE Xplore",
                })

            return {
                "total_results": total_records,
                "page": page,
                "page_size": page_size,
                "papers": papers,
                "query_used": query,
            }
