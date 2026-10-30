"""
BibTeX Exporter for academic papers.
Generates compliant .bib files from normalized paper dictionaries.
"""
from typing import List, Dict, Any, Optional
from pathlib import Path
import re


class BibtexExporter:
    """Exports paper records to BibTeX (.bib) format."""

    @staticmethod
    def _generate_citation_key(paper: Dict[str, Any], index: int) -> str:
        # Generate author_year_word or fallback
        authors = paper.get("authors", [])
        first_author = "unknown"
        if authors:
            if isinstance(authors, list):
                first_author = authors[0].split(",")[0].split()[-1].lower()
            elif isinstance(authors, str):
                first_author = authors.split(",")[0].split()[-1].lower()

        first_author = re.sub(r'[^a-z0-9]', '', first_author)
        year = str(paper.get("year", "2026"))

        title = paper.get("title", "")
        words = [re.sub(r'[^a-z0-9]', '', w.lower()) for w in title.split() if len(w) > 3]
        first_word = words[0] if words else f"rec{index}"

        return f"{first_author}{year}{first_word}"

    @classmethod
    def format_entry(cls, paper: Dict[str, Any], index: int) -> str:
        doc_type = paper.get("doc_type", "article").lower()
        entry_type = "inproceedings" if "conf" in doc_type or "proc" in doc_type else "article"

        key = cls._generate_citation_key(paper, index)

        authors = paper.get("authors", [])
        if isinstance(authors, list):
            author_str = " and ".join(authors)
        else:
            author_str = str(authors)

        fields = [
            f"  author    = {{{author_str}}},",
            f"  title     = {{{paper.get('title', '')}}},",
            f"  year      = {{{paper.get('year', '')}}},",
        ]

        if entry_type == "inproceedings":
            fields.append(f"  booktitle = {{{paper.get('venue', '')}}},")
        else:
            fields.append(f"  journal   = {{{paper.get('venue', '')}}},")

        if paper.get("doi"):
            fields.append(f"  doi       = {{{paper['doi']}}},")
        if paper.get("abstract"):
            fields.append(f"  abstract  = {{{paper['abstract']}}},")
        if paper.get("volume"):
            fields.append(f"  volume    = {{{paper['volume']}}},")
        if paper.get("issue") or paper.get("number"):
            fields.append(f"  number    = {{{paper.get('issue') or paper.get('number')}}},")
        if paper.get("pages"):
            fields.append(f"  pages     = {{{paper['pages']}}},")
        if paper.get("url"):
            fields.append(f"  url       = {{{paper['url']}}},")
        if paper.get("sources"):
            srcs = paper.get("sources")
            src_str = ", ".join(srcs) if isinstance(srcs, list) else str(srcs)
            fields.append(f"  sources   = {{{src_str}}},")
        if paper.get("is_enriched_by_doi"):
            fields.append("  note      = {Enriched via DOI},")
        elif paper.get("database"):
            fields.append(f"  note      = {{Source: {paper['database']}}},")

        body = "\n".join(fields)
        return f"@{entry_type}{{{key},\n{body}\n}}\n"

    @classmethod
    def export(cls, papers: List[Dict[str, Any]], output_path: Optional[Path] = None) -> str:
        entries = [cls.format_entry(p, i + 1) for i, p in enumerate(papers)]
        bibtex_content = "\n".join(entries)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(bibtex_content)

        return bibtex_content
