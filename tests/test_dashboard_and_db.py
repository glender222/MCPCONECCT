"""
Unit and integration tests for Core DB, Audit logger, and Dashboard REST API.
"""
import pytest
from fastapi.testclient import TestClient

from core.db import (
    record_search, get_search_history,
    save_query_iteration, get_query_iterations,
    record_export, get_exports
)
from core.audit import AgentAuditor
from dashboard.app import app

client = TestClient(app)


def test_db_search_history():
    hist_id = record_search(
        agent_name="Codex",
        database="scopus",
        query='TITLE-ABS-KEY ( "unlearnable*" )',
        search_mode="advanced",
        total_hits=42,
        execution_time_ms=120,
        status="success"
    )
    assert hist_id > 0

    history = get_search_history(limit=5)
    assert len(history) >= 1
    recent = history[0]
    assert recent["agent_name"] == "Codex"
    assert recent["database"] == "scopus"
    assert recent["total_hits"] == 42


def test_db_query_iterations():
    iter_id = save_query_iteration(
        title="Test Iteration",
        version="v1.0",
        canonical_query='("unlearnable*") AND ("defens*")',
        notes="Testing PICO storage"
    )
    assert iter_id > 0

    iterations = get_query_iterations()
    assert any(it["title"] == "Test Iteration" for it in iterations)


def test_audit_export_logging():
    exp_id = AgentAuditor.log_export(
        filename="test_export.bib",
        format_type="bibtex",
        database="ieee",
        record_count=15,
        file_path="/tmp/test_export.bib"
    )
    assert exp_id > 0

    exports = get_exports(limit=5)
    assert any(e["filename"] == "test_export.bib" for e in exports)


def test_api_status():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "burp_proxy_enabled" in data
    assert "databases" in data
    assert "scopus" in data["databases"]


def test_api_calibration_translate():
    resp = client.post("/api/calibration/translate", json={"query": '("unlearnable*") AND ("clean")'})
    assert resp.status_code == 200
    data = resp.json()
    assert "scopus" in data
    assert "ieee" in data
    assert "wos" in data
    assert "springer" in data


def test_api_calibration_validate():
    resp = client.post("/api/calibration/validate", json={"database": "scopus", "query": 'TITLE-ABS-KEY ( "test" )'})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True


def test_api_proxy_toggle():
    resp = client.post("/api/proxy/toggle", json={"enabled": True, "proxy_url": "http://127.0.0.1:8080"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["burp_proxy_enabled"] is True
