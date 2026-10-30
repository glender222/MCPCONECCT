"""
Export MCP tools with automatic audit logging and database registration.
"""
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import time
import re

from config import settings
from platforms import get_platform
from exporters.bibtex_exporter import BibtexExporter
from exporters.csv_exporter import CsvExporter
from exporters.ris_exporter import RisExporter
from exporters.citation_formatter import CitationFormatter
from core.audit import AgentAuditor
from core.db import get_corpus_papers


def export_search_results(
    database: str,
    query: str,
    format: str = "bibtex",
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    doc_types: Optional[List[str]] = None,
    max_records: int = 100,
    output_filename: Optional[str] = None,
    agent_name: Optional[str] = "AI Agent (Codex/Claude)",
) -> Dict[str, Any]:
    """
    Executes search, applies platform filters, and exports results directly
    into a standard BibTeX (.bib) or CSV (.csv) file.
    Every export is recorded in the central SQLite registry.
    """
    start_time = time.time()
    fmt = format.lower().strip()
    if fmt not in ("bibtex", "csv", "bib", "ris"):
        raise ValueError(f"Unsupported format '{format}'. Supported formats: 'bibtex', 'csv', 'ris'.")

    platform = get_platform(database)

    try:
        # Retrieve papers
        page_size = min(max_records, 100)
        search_res = platform.search(
            query=query,
            year_start=year_start,
            year_end=year_end,
            doc_types=doc_types,
            page=1,
            page_size=page_size,
        )
        papers = search_res.get("papers", [])

        # Generate filename if not provided
        ext = "bib" if "bib" in fmt else ("ris" if "ris" in fmt else "csv")
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_db = re.sub(r'[^a-zA-Z0-9]', '', database.lower())
            output_filename = f"{safe_db}_export_{timestamp}.{ext}"

        if not output_filename.endswith(f".{ext}"):
            output_filename = f"{output_filename}.{ext}"

        dest_path = settings.EXPORTS_DIR / output_filename

        # Perform export
        if ext == "bib":
            BibtexExporter.export(papers, dest_path)
        elif ext == "ris":
            RisExporter.export(papers, dest_path)
        else:
            CsvExporter.export(papers, dest_path)

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Record export in database
        AgentAuditor.log_export(
            filename=output_filename,
            format_type=ext,
            database=database,
            record_count=len(papers),
            file_path=str(dest_path),
        )

        # Record search history
        AgentAuditor.log_search(
            agent_name=agent_name or "AI Agent",
            database=database,
            query=query,
            search_mode="advanced",
            filters={"year_start": year_start, "year_end": year_end, "doc_types": doc_types, "format": ext},
            total_hits=search_res.get("total_results", len(papers)),
            execution_time_ms=elapsed_ms,
            status="success",
            bibtex_file=str(dest_path) if ext == "bib" else None,
            csv_file=str(dest_path) if ext == "csv" else None,
        )

        preview = []
        for p in papers[:3]:
            preview.append({
                "title": p.get("title"),
                "year": p.get("year"),
                "doi": p.get("doi"),
                "authors": p.get("authors")[:2] if isinstance(p.get("authors"), list) else p.get("authors"),
            })

        return {
            "status": "success",
            "file_path": str(dest_path),
            "filename": output_filename,
            "format": ext,
            "records_exported": len(papers),
            "total_matches_in_database": search_res.get("total_results", len(papers)),
            "preview_samples": preview,
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        AgentAuditor.log_search(
            agent_name=agent_name or "AI Agent",
            database=database,
            query=query,
            search_mode="advanced",
            filters={"year_start": year_start, "year_end": year_end, "doc_types": doc_types},
            total_hits=0,
            execution_time_ms=elapsed_ms,
            status="failed",
            error_message=str(e),
        )
        raise


def export_corpus_file(
    project_id: str = "default_slr",
    format: str = "bibtex",
    citation_style: Optional[str] = None,
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Exports clean, deduplicated papers from the central corpus_papers table
    into standard academic formats: BibTeX (.bib), CSV (.csv), RIS (.ris), or formatted citations (.txt).

    Args:
        project_id: Project identifier (defaults to 'default_slr').
        format: Export format ('bibtex', 'csv', 'ris', 'txt').
        citation_style: Citation style for .txt exports ('ieee', 'apa7', 'bibitem').
        output_filename: Optional custom output filename.
    """
    fmt = format.lower().strip()
    if fmt not in ("bibtex", "csv", "ris", "bib", "txt"):
        raise ValueError(f"Unsupported format '{format}'. Choose from 'bibtex', 'csv', 'ris', 'txt'.")

    papers = get_corpus_papers(project_id=project_id, limit=10000)
    if not papers:
        return {
            "status": "empty",
            "project_id": project_id,
            "message": "No papers found in corpus for this project.",
            "records_exported": 0,
        }

    ext = "bib" if "bib" in fmt else ("ris" if "ris" in fmt else ("csv" if fmt == "csv" else "txt"))
    if not output_filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"corpus_{project_id}_{timestamp}.{ext}"

    if not output_filename.endswith(f".{ext}"):
        output_filename = f"{output_filename}.{ext}"

    dest_path = settings.EXPORTS_DIR / output_filename

    if ext == "bib":
        BibtexExporter.export(papers, dest_path)
    elif ext == "csv":
        CsvExporter.export(papers, dest_path)
    elif ext == "ris":
        RisExporter.export(papers, dest_path)
    elif ext == "txt":
        style = (citation_style or "ieee").lower()
        formatted_lines = [CitationFormatter.format_paper(p, style=style, index=i + 1) for i, p in enumerate(papers)]
        dest_path.write_text("\n\n".join(formatted_lines), encoding="utf-8")

    AgentAuditor.log_export(
        filename=output_filename,
        format_type=ext,
        database="corpus",
        record_count=len(papers),
        file_path=str(dest_path),
    )

    return {
        "status": "success",
        "project_id": project_id,
        "file_path": str(dest_path),
        "filename": output_filename,
        "format": ext,
        "records_exported": len(papers),
    }


def register_export_tools(mcp) -> None:
    mcp.tool()(export_search_results)
    mcp.tool()(export_corpus_file)

