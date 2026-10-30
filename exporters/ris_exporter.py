"""
RIS Exporter for academic papers.
Generates compliant .ris files for Rayyan, Covidence, Zotero, Mendeley, and EndNote.
"""
from typing import List, Dict, Any, Optional
from pathlib import Path


class RisExporter:
    """Exports paper records to Research Information Systems (.ris) format."""

    @staticmethod
    def _map_doc_type(doc_type: str) -> str:
        dt = (doc_type or "").lower()
        if "conf" in dt or "proc" in dt:
            return "CONF"
        if "book" in dt or "chap" in dt:
            return "BOOK"
        return "JOUR"

    @classmethod
    def format_entry(cls, paper: Dict[str, Any]) -> str:
        lines = []
        ty = cls._map_doc_type(paper.get("doc_type", "article"))
        lines.append(f"TY  - {ty}")

        title = paper.get("title", "")
        if title:
            lines.append(f"TI  - {title}")

        authors = paper.get("authors", [])
        if isinstance(authors, list):
            for a in authors:
                if a:
                    lines.append(f"AU  - {a}")
        elif isinstance(authors, str) and authors:
            for a in authors.split(";"):
                clean_a = a.strip()
                if clean_a:
                    lines.append(f"AU  - {clean_a}")

        year = paper.get("year")
        if year:
            lines.append(f"PY  - {year}")

        venue = paper.get("venue", "")
        if venue:
            lines.append(f"T2  - {venue}")

        doi = paper.get("doi", "")
        if doi:
            lines.append(f"DO  - {doi}")

        abstract = paper.get("abstract", "")
        if abstract:
            lines.append(f"AB  - {abstract}")

        keywords = paper.get("keywords", [])
        if isinstance(keywords, list):
            for kw in keywords:
                if kw:
                    lines.append(f"KW  - {kw}")
        elif isinstance(keywords, str) and keywords:
            for kw in keywords.split(";"):
                clean_kw = kw.strip()
                if clean_kw:
                    lines.append(f"KW  - {clean_kw}")

        url = paper.get("url", "")
        if url:
            lines.append(f"UR  - {url}")

        sources = paper.get("sources", [])
        if isinstance(sources, list) and sources:
            lines.append(f"DB  - {', '.join(sources)}")
        elif paper.get("database"):
            lines.append(f"DB  - {paper['database']}")

        lines.append("ER  - \n")
        return "\n".join(lines)

    @classmethod
    def export(cls, papers: List[Dict[str, Any]], output_path: Optional[Path] = None) -> str:
        entries = [cls.format_entry(p) for p in papers]
        ris_content = "\n".join(entries)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(ris_content)

        return ris_content
