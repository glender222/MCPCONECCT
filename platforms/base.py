"""
Base interface and canonical data models for academic platform adapters.
"""
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import hashlib
import re
from pydantic import BaseModel, Field

from core.http_client import AcademicHttpClient, SessionStore
from config import settings


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """
    Cleans and canonicalizes a DOI identifier.
    Strips URL prefixes, lowercases, and checks 10.xxxx structure.
    """
    if not doi:
        return None
    d = str(doi).strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    d = d.strip()
    if d.startswith("10.") and "/" in d:
        return d
    return None


def normalize_title(title: str) -> str:
    """
    Normalizes a paper title for deduplication:
    Removes HTML tags, punctuation, extra whitespace, and lowercases.
    """
    if not title:
        return ""
    clean = re.sub(r"<[^>]+>", " ", str(title))
    clean = re.sub(r"[^\w\s]", " ", clean)
    return " ".join(clean.lower().split())


def generate_bibtex_key(authors: List[str], year: Optional[int], title: str) -> str:
    """
    Generates a canonical BibTeX key: FirstAuthorLastNameYearFirstTitleWord
    Example: smith2023deep
    """
    first_author = "unknown"
    if authors and len(authors) > 0:
        raw_author = authors[0].strip()
        if "," in raw_author:
            first_author = raw_author.split(",")[0].strip()
        else:
            parts = raw_author.split()
            first_author = parts[-1].strip() if parts else "unknown"

    first_author_clean = re.sub(r"[^\w]", "", first_author.lower()) or "unknown"
    year_str = str(year) if year else "nodate"

    norm_title = normalize_title(title)
    words = [w for w in norm_title.split() if w not in ("a", "an", "the", "on", "in", "of", "for", "with", "and", "to")]
    first_word = words[0] if words else "paper"
    first_word_clean = re.sub(r"[^\w]", "", first_word.lower())

    return f"{first_author_clean}{year_str}{first_word_clean}"


class CanonicalPaper(BaseModel):
    """Canonical data contract for academic papers across all databases."""
    record_id: str = ""
    doi: Optional[str] = None
    title: str
    normalized_title: str = ""
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doc_type: str = "other"
    abstract: str = ""
    keywords: List[str] = Field(default_factory=list)
    url: str = ""
    sources: List[str] = Field(default_factory=list)
    raw_bibtex_key: str = ""
    duplicate_count: int = 1
    is_enriched_by_doi: bool = False
    citation_count: int = 0
    prisma_stage: str = "identification"

    def finalize(self) -> "CanonicalPaper":
        """Finalizes normalization, DOI cleaning, and generates 24-character SHA-256 record_id."""
        self.doi = normalize_doi(self.doi)
        self.normalized_title = normalize_title(self.title)

        if self.year is not None:
            try:
                self.year = int(self.year)
            except Exception:
                self.year = None

        if not self.raw_bibtex_key:
            self.raw_bibtex_key = generate_bibtex_key(self.authors, self.year, self.title)

        if not self.record_id:
            if self.doi:
                raw = f"doi:{self.doi}"
            else:
                first_author = (self.authors[0] if self.authors else "anon").lower()
                raw = f"title:{self.normalized_title}|year:{self.year}|author:{first_author}"
            self.record_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

        return self

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary with backward compatibility for legacy callers."""
        d = self.model_dump()
        d["database"] = self.sources[0] if self.sources else "academic"
        return d


class AcademicPlatform(ABC):
    """Abstract base class for academic database integrations."""

    def __init__(self, name: str):
        self.name = name.lower()
        self.http_client_factory = AcademicHttpClient(self.name)

    @property
    def session_config(self) -> Dict[str, Any]:
        return SessionStore.get_session(self.name)

    def get_base_url(self, default_url: str) -> str:
        """Returns configured base URL or default, respecting EZProxy/OpenAthens overrides."""
        return settings.get_base_url(self.name, default_url)

    @abstractmethod
    def search(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """
        Executes search on the database.
        Returns:
            {
                "total_results": int,
                "page": int,
                "page_size": int,
                "papers": List[Dict[str, Any]],
                "query_used": str
            }
        """
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Tests whether the current session/credentials are valid.
        Returns:
            {
                "database": str,
                "connected": bool,
                "status_code": Optional[int],
                "message": str
            }
        """
        pass

    @abstractmethod
    def get_paper_count(
        self,
        query: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
    ) -> int:
        """Returns total hit count for a query without downloading full papers."""
        pass
