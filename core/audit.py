"""
Audit and telemetry logger for MCPCONECCT.
Automatically captures and logs all calls made by AI agents (Codex, Claude, Antigravity)
and the Web Dashboard into the central SQLite database.
"""
from typing import Dict, Any, Optional
import time
import logging
from core.db import record_search, record_export

logger = logging.getLogger("mcpconecct.audit")


class AgentAuditor:
    """Records MCP and UI interactions."""

    @staticmethod
    def log_search(
        agent_name: str,
        database: str,
        query: str,
        search_mode: str = "advanced",
        filters: Optional[Dict[str, Any]] = None,
        total_hits: int = 0,
        execution_time_ms: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
        bibtex_file: Optional[str] = None,
        csv_file: Optional[str] = None,
    ) -> int:
        return record_search(
            agent_name=agent_name,
            database=database,
            query=query,
            search_mode=search_mode,
            filters=filters,
            total_hits=total_hits,
            execution_time_ms=execution_time_ms,
            status=status,
            error_message=error_message,
            bibtex_file=bibtex_file,
            csv_file=csv_file,
        )

    @staticmethod
    def log_export(
        filename: str,
        format_type: str,
        database: str,
        record_count: int,
        file_path: str,
    ) -> int:
        return record_export(
            filename=filename,
            format_type=format_type,
            database=database,
            record_count=record_count,
            file_path=file_path,
        )
