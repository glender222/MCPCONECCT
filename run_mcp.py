#!/usr/bin/env python3
"""
CLI entry point for MCPCONECCT.
Launches the MCP server over stdio (default) or SSE.
"""
import argparse
import sys
import os
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import settings
from mcp_server.server import run_server


def main():
    parser = argparse.ArgumentParser(description="MCPCONECCT: Academic Search & Export MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (stdio for Claude/Cursor/Codex, sse for web/remote)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind for SSE transport (default: 8765)",
    )
    parser.add_argument(
        "--burp",
        action="store_true",
        help="Route all HTTP requests through Burp Suite (127.0.0.1:8080)",
    )
    parser.add_argument(
        "--proxy-url",
        default="http://127.0.0.1:8080",
        help="Burp Suite proxy URL (default: http://127.0.0.1:8080)",
    )

    args = parser.parse_args()

    if args.burp:
        settings.BURP_PROXY_ENABLED = True
        settings.BURP_PROXY_URL = args.proxy_url
        settings.DISABLE_SSL_VERIFY = True
        os.environ["BURP_PROXY_ENABLED"] = "true"
        os.environ["BURP_PROXY_URL"] = args.proxy_url
        os.environ["DISABLE_SSL_VERIFY"] = "true"

    run_server(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
