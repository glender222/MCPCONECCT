"""
FastAPI Web Dashboard Application for MCPCONECCT.
Provides visual interface for academic search, PICO calibration,
Burp Suite session management, and agent observability.
"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from config import settings
from dashboard.routes.api import router as api_router
from core.db import get_search_history, get_query_iterations, get_exports
from core.http_client import SessionStore

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="MCPCONECCT Dashboard",
    description="Academic Search, PICO Calibration & Agent Observability Hub",
    version="1.0.0",
)

# Mount API
app.include_router(api_router)

# Mount Static & Templates
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request):
    store = SessionStore.load_store()
    history = get_search_history(limit=10)
    iterations = get_query_iterations()
    exports = get_exports(limit=10)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "burp_enabled": settings.BURP_PROXY_ENABLED,
            "burp_url": settings.BURP_PROXY_URL,
            "sessions": store,
            "history": history,
            "iterations_count": len(iterations),
            "exports_count": len(exports),
            "active_page": "dashboard",
        },
    )


@app.get("/connections", response_class=HTMLResponse)
def connections_page(request: Request):
    store = SessionStore.load_store()
    return templates.TemplateResponse(
        request=request,
        name="connections.html",
        context={
            "burp_enabled": settings.BURP_PROXY_ENABLED,
            "burp_url": settings.BURP_PROXY_URL,
            "sessions": store,
            "active_page": "connections",
        },
    )


@app.get("/calibration", response_class=HTMLResponse)
def calibration_page(request: Request):
    iterations = get_query_iterations()
    return templates.TemplateResponse(
        request=request,
        name="calibration.html",
        context={
            "burp_enabled": settings.BURP_PROXY_ENABLED,
            "iterations": iterations,
            "active_page": "calibration",
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    store = SessionStore.load_store()
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "burp_enabled": settings.BURP_PROXY_ENABLED,
            "sessions": store,
            "active_page": "search",
        },
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    history = get_search_history(limit=100)
    exports = get_exports(limit=100)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "burp_enabled": settings.BURP_PROXY_ENABLED,
            "history": history,
            "exports": exports,
            "active_page": "history",
        },
    )
