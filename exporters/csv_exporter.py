"""
CSV Exporter for academic papers.
Generates structured CSV files compatible with Parsifal, Covidence, Rayyan, and R.
"""
from typing import List, Dict, Any, Optional
from pathlib import Path
import csv
import io


class CsvExporter:
    """Exports paper records to CSV format with standard SLR columns."""

    HEADERS = [
        "DOI",
        "Title",
        "Authors",
        "Year",
        "Venue",
        "DocumentType",
        "Abstract",
        "URL",
        "Database",
        "CitationCount",
    ]

    @classmethod
    def export(cls, papers: List[Dict[str, Any]], output_path: Optional[Path] = None) -> str:
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)

        # Write header
        writer.writerow(cls.HEADERS)

        # Write rows
        for paper in papers:
            authors = paper.get("authors", [])
            if isinstance(authors, list):
                author_str = "; ".join(authors)
            else:
                author_str = str(authors)

            row = [
                paper.get("doi", ""),
                paper.get("title", ""),
                author_str,
                paper.get("year", ""),
                paper.get("venue", ""),
                paper.get("doc_type", ""),
                paper.get("abstract", ""),
                paper.get("url", ""),
                paper.get("database", ""),
                paper.get("citation_count", 0),
            ]
            writer.writerow(row)

        content = output.getvalue()

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                f.write(content)

        return content
