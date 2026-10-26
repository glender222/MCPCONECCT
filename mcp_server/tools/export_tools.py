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
from core.audit import AgentAuditor


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
    if fmt not in ("bibtex", "csv", "bib"):
        raise ValueError(f"Unsupported format '{format}'. Supported formats: 'bibtex', 'csv'.")

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
        ext = "bib" if "bib" in fmt else "csv"
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


def register_export_tools(mcp) -> None:
    mcp.tool()(export_search_results)
