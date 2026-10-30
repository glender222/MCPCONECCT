"""
Academic Citation Formatter for MCPCONECCT.
Formats paper records into standardized plaintext citations: IEEE, APA 7, and LaTeX \\bibitem.
"""
from typing import Dict, Any, List, Optional
import re

from exporters.bibtex_exporter import BibtexExporter


class CitationFormatter:
    """Formats canonical paper metadata into academic citation strings."""

    @staticmethod
    def _format_initials(name: str) -> str:
        """Converts 'Hanxun Huang' to 'H. Huang' or 'Huang, Hanxun' to 'H. Huang'."""
        name = name.strip()
        if "," in name:
            parts = name.split(",", 1)
            last = parts[0].strip()
            first = parts[1].strip()
            first_initial = f"{first[0]}." if first else ""
            return f"{first_initial} {last}".strip()
        parts = name.split()
        if len(parts) == 1:
            return parts[0]
        initials = " ".join(f"{p[0]}." for p in parts[:-1])
        return f"{initials} {parts[-1]}"

    @staticmethod
    def _format_apa_author(name: str) -> str:
        """Converts 'Hanxun Huang' to 'Huang, H.'."""
        name = name.strip()
        if "," in name:
            parts = name.split(",", 1)
            last = parts[0].strip()
            first = parts[1].strip()
            initials = " ".join(f"{p[0]}." for p in first.split()) if first else ""
            return f"{last}, {initials}".strip()
        parts = name.split()
        if len(parts) == 1:
            return parts[0]
        initials = " ".join(f"{p[0]}." for p in parts[:-1])
        return f"{parts[-1]}, {initials}"

    @classmethod
    def format_ieee(cls, paper: Dict[str, Any], index: int = 1) -> str:
        """
        Formats as IEEE citation style:
        [1] H. Huang et al., "Title," Venue, 2021, doi: 10.1109/xxx.
        """
        authors = paper.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]

        if not authors:
            author_str = "Anon."
        elif len(authors) > 3:
            first = cls._format_initials(authors[0])
            author_str = f"{first} et al."
        elif len(authors) == 1:
            author_str = cls._format_initials(authors[0])
        elif len(authors) == 2:
            author_str = f"{cls._format_initials(authors[0])} and {cls._format_initials(authors[1])}"
        else:
            author_str = f"{cls._format_initials(authors[0])}, {cls._format_initials(authors[1])}, and {cls._format_initials(authors[2])}"

        title = paper.get("title", "").strip().rstrip(".,")
        venue = paper.get("venue", "").strip()
        year = str(paper.get("year", "")).strip()
        doi = paper.get("doi", "").strip()

        line = f"[{index}] {author_str}, \"{title},\""
        if venue:
            line += f" {venue},"
        if year:
            line += f" {year}"
        if doi:
            line += f", doi: {doi}."
        else:
            line += "."
        return line

    @classmethod
    def format_apa7(cls, paper: Dict[str, Any]) -> str:
        """
        Formats as APA 7th edition citation style:
        Huang, H., Ma, X., & Bailey, J. (2021). Title. Venue. https://doi.org/10.xxxx
        """
        authors = paper.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]

        if not authors:
            author_str = "Unknown"
        elif len(authors) == 1:
            author_str = cls._format_apa_author(authors[0])
        elif len(authors) == 2:
            author_str = f"{cls._format_apa_author(authors[0])}, & {cls._format_apa_author(authors[1])}"
        elif len(authors) <= 20:
            formatted = [cls._format_apa_author(a) for a in authors]
            author_str = ", ".join(formatted[:-1]) + f", & {formatted[-1]}"
        else:
            formatted = [cls._format_apa_author(a) for a in authors[:19]]
            author_str = ", ".join(formatted) + f", ... {cls._format_apa_author(authors[-1])}"

        year = str(paper.get("year", "n.d.")).strip() or "n.d."
        title = paper.get("title", "").strip().rstrip(".")
        venue = paper.get("venue", "").strip()
        doi = paper.get("doi", "").strip()

        res = f"{author_str} ({year}). {title}."
        if venue:
            res += f" {venue}."
        if doi:
            doi_url = f"https://doi.org/{doi}" if not doi.startswith("http") else doi
            res += f" {doi_url}"
        return res

    @classmethod
    def format_bibitem(cls, paper: Dict[str, Any], index: int = 1) -> str:
        """
        Formats as LaTeX \\bibitem entry:
        \\bibitem{huang2021unlearnable} H. Huang et al., ``Title,'' \\textit{Venue}, 2021.
        """
        key = paper.get("raw_bibtex_key") or BibtexExporter._generate_citation_key(paper, index)
        authors = paper.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]

        if not authors:
            author_str = "Anon."
        elif len(authors) > 3:
            first = cls._format_initials(authors[0])
            author_str = f"{first} et al."
        else:
            author_str = ", ".join(cls._format_initials(a) for a in authors)

        title = paper.get("title", "").strip().rstrip(".,")
        venue = paper.get("venue", "").strip()
        year = str(paper.get("year", "")).strip()

        venue_str = f"\\textit{{{venue}}}" if venue else ""
        middle_parts = [f"``{title},''"]
        if venue_str:
            middle_parts.append(venue_str)
        if year:
            middle_parts.append(year)
        middle = ", ".join(middle_parts)
        return f"\\bibitem{{{key}}} {author_str}, {middle}."

    @classmethod
    def format_paper(
        cls,
        paper: Dict[str, Any],
        style: str = "ieee",
        index: int = 1
    ) -> str:
        """Dispatcher for formatted citation strings."""
        s = style.lower().strip()
        if s == "ieee":
            return cls.format_ieee(paper, index=index)
        elif s in ("apa", "apa7"):
            return cls.format_apa7(paper)
        elif s in ("bibitem", "latex", "latex_bibitem"):
            return cls.format_bibitem(paper, index=index)
        elif s == "bibtex":
            return BibtexExporter.format_entry(paper, index)
        return cls.format_ieee(paper, index=index)
