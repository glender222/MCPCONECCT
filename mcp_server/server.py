"""
MCPCONECCT Model Context Protocol (MCP) Server.
Initializes the MCP Server instance, attaches all academic tools,
resources, and prompts, and supports stdio and SSE transports.
"""
from typing import Dict, Any
import logging
import json

from mcp.server.mcpserver import MCPServer

from config import settings
from mcp_server.tools.validation_tools import register_validation_tools
from mcp_server.tools.auth_tools import register_auth_tools
from mcp_server.tools.search_tools import register_search_tools
from mcp_server.tools.export_tools import register_export_tools
from mcp_server.tools.research_tools import register_research_tools
from core.http_client import SessionStore

logger = logging.getLogger("mcpconecct.mcp_server")


def create_server(name: str = "mcpconecct") -> MCPServer:
    """
    Creates and configures the MCPCONECCT server instance.
    Registers tools for query validation, Burp Suite routing,
    authenticated academic search, and BibTeX/CSV exports.
    """
    server = MCPServer(
        name=name,
        instructions=(
            "MCPCONECCT is an automated Model Context Protocol server for academic literature research "
            "(Systematic Literature Reviews / SLR). It connects to Scopus, IEEE Xplore, Web of Science, "
            "and SpringerLink. It validates complex boolean queries against platform-specific syntax "
            "and limits (such as IEEE's 10-wildcard maximum and Scopus hyphen rules), routes traffic "
            "through Burp Suite (127.0.0.1:8080) for real-time inspection, manages session cookies, "
            "and exports search results directly to clean BibTeX (.bib) and CSV (.csv) files."
        ),
    )

    # Register tools
    register_validation_tools(server)
    register_auth_tools(server)
    register_search_tools(server)
    register_export_tools(server)
    register_research_tools(server)

    # Register Resources
    @server.resource("mcp://status")
    def get_status_resource() -> str:
        """Returns the current status of all databases and proxy configuration."""
        store = SessionStore.load_store()
        return json.dumps({
            "burp_proxy_enabled": settings.BURP_PROXY_ENABLED,
            "burp_proxy_url": settings.BURP_PROXY_URL,
            "exports_dir": str(settings.EXPORTS_DIR),
            "databases": {k: {"status": v.get("status"), "cookies": len(v.get("cookies", {}))} for k, v in store.items()},
        }, indent=2)

    @server.resource("mcp://syntax-rules")
    def get_syntax_rules_resource() -> str:
        """Returns database syntax rules and constraints."""
        if settings.SYNTAX_RULES_FILE.exists():
            with open(settings.SYNTAX_RULES_FILE, "r", encoding="utf-8") as f:
                return f.read()
        return "{}"

    # Register Prompts
    @server.prompt()
    def calibrate_slr_search(
        pico_query: str,
        databases: str = "scopus,ieee,wos,springer",
        year_start: int = 2020,
        year_end: int = 2026,
    ) -> str:
        """
        Prompt template to guide the AI agent through query calibration,
        syntax validation, count checks, and initial screening export.
        """
        return (
            f"You are calibrating an academic search for a Systematic Literature Review.\n"
            f"Input Query: {pico_query}\n"
            f"Databases to query: {databases}\n"
            f"Publication Years: {year_start} to {year_end}\n\n"
            f"Follow these steps:\n"
            f"1. Use 'validate_search_string' for each database to detect wildcard limits or syntax errors.\n"
            f"2. Use 'translate_search_string' to obtain the exact platform-specific query.\n"
            f"3. Check total paper counts using 'get_paper_count' for both unconstrained and filtered queries.\n"
            f"4. Once calibrated, execute 'export_search_results' to save the records as BibTeX (.bib) and CSV (.csv)."
        )

    return server


# Global server instance
mcp_server = create_server("mcpconecct")


def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000) -> None:
    """Runs the MCP server with the specified transport."""
    if transport == "stdio":
        mcp_server.run(transport="stdio")
    elif transport == "sse":
        mcp_server.run(transport="sse", host=host, port=port)
    else:
        raise ValueError(f"Unknown transport: {transport}. Use 'stdio' or 'sse'.")
