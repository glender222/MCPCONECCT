#!/usr/bin/env python3
"""
Launcher for MCPCONECCT Web UX/UI Dashboard.
Starts the FastAPI application on http://127.0.0.1:8765.
"""
import argparse
import sys
import uvicorn
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main():
    parser = argparse.ArgumentParser(description="MCPCONECCT Web Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765)")
    parser.add_argument("--reload", action="store_true", help="Enable hot reload")

    args = parser.parse_args()

    print(f"\n🚀 Starting MCPCONECCT Web Dashboard on http://{args.host}:{args.port}")
    print("👉 Open http://localhost:8765 in your browser.\n")

    uvicorn.run("dashboard.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
