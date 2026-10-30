"""
Search MCP tools with automatic audit logging.
"""
from typing import Dict, Any, List, Optional
import time
from platforms import get_platform
from core.audit import AgentAuditor


def search_papers(
    database: str,
    query: str,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    doc_types: Optional[List[str]] = None,
    page: int = 1,
    page_size: int = 25,
    agent_name: Optional[str] = "AI Agent (Codex/Claude)",
) -> Dict[str, Any]:
    """
    Executes an academic literature search using the configured session or API.
    Applies year and document type filters and returns a structured list of papers.
    Every call is automatically logged into the central SQLite audit database.

    Args:
        database: Target platform ('scopus', 'ieee', 'wos', 'springer').
        query: The platform-specific search query string.
        year_start: Optional starting publication year (e.g. 2020).
        year_end: Optional ending publication year (e.g. 2026).
        doc_types: Optional list of document types (e.g. ['Article', 'Conference Paper']).
        page: Page number for pagination (defaults to 1).
        page_size: Number of records per page (defaults to 25).
        agent_name: Name of the caller agent (e.g. 'Codex', 'Claude Code', 'Antigravity').
    """
    start_time = time.time()
    platform = get_platform(database)

    try:
        res = platform.search(
            query=query,
            year_start=year_start,
            year_end=year_end,
            doc_types=doc_types,
            page=page,
            page_size=page_size,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)

        AgentAuditor.log_search(
            agent_name=agent_name or "AI Agent",
            database=database,
            query=query,
            search_mode="advanced",
            filters={"year_start": year_start, "year_end": year_end, "doc_types": doc_types},
            total_hits=res.get("total_results", len(res.get("papers", []))),
            execution_time_ms=elapsed_ms,
            status="success",
        )
        return res
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


def get_paper_count(
    database: str,
    query: str,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    doc_types: Optional[List[str]] = None,
    agent_name: Optional[str] = "AI Agent (Codex/Claude)",
) -> Dict[str, Any]:
    """
    Retrieves the total count of papers matching a search query and filters.
    """
    platform = get_platform(database)
    count = platform.get_paper_count(
        query=query,
        year_start=year_start,
        year_end=year_end,
        doc_types=doc_types,
    )
    return {
        "database": database,
        "total_count": count,
        "year_start": year_start,
        "year_end": year_end,
        "doc_types": doc_types,
    }


def fetch_and_ingest_corpus(
    database: str,
    query: str,
    max_records: int = 50,
    project_id: str = "default_slr",
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    doc_types: Optional[List[str]] = None,
    enrich_missing_abstracts: bool = True,
) -> Dict[str, Any]:
    """
    Streams, caches, enriches and ingests academic papers directly into the central SQLite corpus.
    Includes anti-bot pacing, exponential backoff, OpenAlex DOI enrichment, and deduplication.
    """
    from core.stream_fetcher import BulkStreamFetcher
    fetcher = BulkStreamFetcher(
        database=database,
        query=query,
        max_records=max_records,
        page_size=25,
        year_start=year_start,
        year_end=year_end,
        doc_types=doc_types,
        project_id=project_id,
        enrich_missing_abstracts=enrich_missing_abstracts,
    )
    return fetcher.execute()


def deduplicate_project_corpus(
    project_id: str = "default_slr",
    fuzzy_threshold: float = 0.92,
) -> Dict[str, Any]:
    """
    Runs cross-database 2-phase deduplication on all papers stored in the central corpus for a project.
    Phase 1 matches exact DOI; Phase 2 matches fuzzy title (>=0.92) + year + first author.
    """
    from core.deduplicator import CorpusDeduplicator
    return CorpusDeduplicator.deduplicate_database_corpus(project_id, fuzzy_threshold)


def register_search_tools(mcp) -> None:
    mcp.tool()(search_papers)
    mcp.tool()(get_paper_count)
    mcp.tool()(fetch_and_ingest_corpus)
    mcp.tool()(deduplicate_project_corpus)

