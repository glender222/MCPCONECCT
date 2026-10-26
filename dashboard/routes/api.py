"""
REST API routes for MCPCONECCT Web Dashboard.
Exposes endpoints for connections, calibration, search, history, and exports.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import os
from pathlib import Path
import time

from config import settings
from core.http_client import SessionStore, parse_curl_command
from core.query_validator import QueryValidator
from core.query_translator import QueryTranslator
from core.db import (
    get_search_history, get_query_iterations, save_query_iteration,
    get_exports, record_search, record_export
)
from core.audit import AgentAuditor
from platforms import get_platform, PLATFORMS

router = APIRouter(prefix="/api")


# --- Status & Proxy ---

@router.get("/status")
def get_system_status():
    store = SessionStore.load_store()
    db_statuses = {}
    for name, adapter in PLATFORMS.items():
        sess = store.get(name, {})
        db_statuses[name] = {
            "status": sess.get("status", "unconfigured"),
            "cookies_count": len(sess.get("cookies", {})),
            "has_api_key": bool(sess.get("api_key")),
        }

    return {
        "burp_proxy_enabled": settings.BURP_PROXY_ENABLED,
        "burp_proxy_url": settings.BURP_PROXY_URL,
        "databases": db_statuses,
        "exports_dir": str(settings.EXPORTS_DIR),
    }


class ProxyToggleRequest(BaseModel):
    enabled: bool
    proxy_url: Optional[str] = "http://127.0.0.1:8080"


@router.post("/proxy/toggle")
def toggle_burp_proxy(req: ProxyToggleRequest):
    settings.BURP_PROXY_ENABLED = req.enabled
    if req.proxy_url:
        settings.BURP_PROXY_URL = req.proxy_url
    os.environ["BURP_PROXY_ENABLED"] = str(req.enabled).lower()
    os.environ["BURP_PROXY_URL"] = settings.BURP_PROXY_URL
    return {
        "status": "success",
        "burp_proxy_enabled": settings.BURP_PROXY_ENABLED,
        "proxy_url": settings.BURP_PROXY_URL,
    }


# --- Connections & Auth ---

@router.get("/connections")
def list_connections():
    store = SessionStore.load_store()
    return store


class UpdateConnectionRequest(BaseModel):
    database: str
    cookies: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = None
    api_key: Optional[str] = None


@router.post("/connections/update")
def update_connection(req: UpdateConnectionRequest):
    updated = SessionStore.update_session(
        database=req.database,
        cookies=req.cookies,
        headers=req.headers,
        api_key=req.api_key,
        status="configured",
    )
    return {"status": "success", "database": req.database, "session": updated}


class ImportCurlRequest(BaseModel):
    database: str
    curl_command: str


@router.post("/connections/import-curl")
def import_curl_endpoint(req: ImportCurlRequest):
    db = req.database.lower().strip()
    parsed = parse_curl_command(req.curl_command)
    updated = SessionStore.update_session(
        database=db,
        cookies=parsed.get("cookies"),
        headers=parsed.get("headers"),
        status="configured",
    )
    return {
        "status": "success",
        "database": db,
        "target_url": parsed.get("url"),
        "cookies_imported": list(parsed.get("cookies", {}).keys()),
        "headers_imported": list(parsed.get("headers", {}).keys()),
    }


class TestConnectionRequest(BaseModel):
    database: str


@router.post("/connections/test")
def test_connection_endpoint(req: TestConnectionRequest):
    platform = get_platform(req.database)
    res = platform.test_connection()
    res["burp_proxy_active"] = settings.BURP_PROXY_ENABLED
    return res


# --- Calibration & PICO Studio ---

class TranslateRequest(BaseModel):
    query: str


@router.post("/calibration/translate")
def translate_query(req: TranslateRequest):
    return QueryTranslator.translate_all(req.query)


class ValidateRequest(BaseModel):
    database: str
    query: str


@router.post("/calibration/validate")
def validate_query(req: ValidateRequest):
    report = QueryValidator.validate(req.database, req.query)
    return report.model_dump()


class ProbeCountRequest(BaseModel):
    query: str
    year_start: Optional[int] = 2020
    year_end: Optional[int] = 2026
    doc_types: Optional[List[str]] = ["Article", "Conference Paper"]


@router.post("/calibration/probe-count")
def probe_count(req: ProbeCountRequest):
    """Probes paper counts across all 4 platforms with and without filters."""
    translations = QueryTranslator.translate_all(req.query)
    results = {}

    for db_name, adapter in PLATFORMS.items():
        db_query = translations.get(db_name, req.query)
        try:
            raw_count = adapter.get_paper_count(db_query)
            filtered_count = adapter.get_paper_count(
                db_query,
                year_start=req.year_start,
                year_end=req.year_end,
                doc_types=req.doc_types,
            )
            results[db_name] = {
                "unfiltered_count": raw_count,
                "filtered_count": filtered_count,
                "noise_filtered": max(0, raw_count - filtered_count),
                "query_used": db_query,
                "status": "ok",
            }
        except Exception as e:
            results[db_name] = {
                "unfiltered_count": 0,
                "filtered_count": 0,
                "error": str(e),
                "query_used": db_query,
                "status": "error",
            }

    return results


class SaveIterationRequest(BaseModel):
    title: str
    version: str
    canonical_query: str
    pico_data: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    counts: Optional[Dict[str, Any]] = None


@router.post("/calibration/iterations")
def save_iteration(req: SaveIterationRequest):
    iter_id = save_query_iteration(
        title=req.title,
        version=req.version,
        canonical_query=req.canonical_query,
        pico_data=req.pico_data,
        notes=req.notes,
        counts=req.counts,
    )
    return {"status": "success", "iteration_id": iter_id}


@router.get("/calibration/iterations")
def list_iterations():
    return get_query_iterations()


# --- Search & Export ---

class SearchExecutionRequest(BaseModel):
    database: str
    query: str
    search_mode: Optional[str] = "advanced"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    doc_types: Optional[List[str]] = None
    page: int = 1
    page_size: int = 25
    agent_name: Optional[str] = "Web UI"


@router.post("/search")
def execute_search(req: SearchExecutionRequest):
    start = time.time()
    platform = get_platform(req.database)
    try:
        res = platform.search(
            query=req.query,
            year_start=req.year_start,
            year_end=req.year_end,
            doc_types=req.doc_types,
            page=req.page,
            page_size=req.page_size,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        AgentAuditor.log_search(
            agent_name=req.agent_name,
            database=req.database,
            query=req.query,
            search_mode=req.search_mode,
            filters={"year_start": req.year_start, "year_end": req.year_end, "doc_types": req.doc_types},
            total_hits=res.get("total_results", len(res.get("papers", []))),
            execution_time_ms=elapsed_ms,
            status="success",
        )
        return res
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        AgentAuditor.log_search(
            agent_name=req.agent_name,
            database=req.database,
            query=req.query,
            search_mode=req.search_mode,
            filters={"year_start": req.year_start, "year_end": req.year_end, "doc_types": req.doc_types},
            total_hits=0,
            execution_time_ms=elapsed_ms,
            status="failed",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def list_history(limit: int = 50, database: Optional[str] = None):
    return get_search_history(limit=limit, database=database)


class ExportExecutionRequest(BaseModel):
    database: str
    query: str
    format: str = "bibtex"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    max_records: int = 50
    agent_name: Optional[str] = "Web UI"


@router.post("/export")
def execute_export(req: ExportExecutionRequest):
    from mcp_server.tools.export_tools import export_search_results
    try:
        res = export_search_results(
            database=req.database,
            query=req.query,
            format=req.format,
            year_start=req.year_start,
            year_end=req.year_end,
            max_records=req.max_records,
            agent_name=req.agent_name,
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exports")
def list_exports(limit: int = 50):
    return get_exports(limit=limit)


@router.get("/exports/{filename}/content")
def get_export_content(filename: str):
    safe_name = os.path.basename(filename)
    path = settings.EXPORTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return {
            "filename": safe_name,
            "format": "bibtex" if safe_name.endswith(".bib") else "csv",
            "size_bytes": path.stat().st_size,
            "content": content,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{filename}")
def download_file(filename: str):
    safe_name = os.path.basename(filename)
    path = settings.EXPORTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    media_type = "application/x-bibtex" if safe_name.endswith(".bib") else "text/csv"
    return FileResponse(path, filename=safe_name, media_type=media_type)
