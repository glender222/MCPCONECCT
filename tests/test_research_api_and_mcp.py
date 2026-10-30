import pytest
import tempfile
import uuid
from pathlib import Path
from fastapi.testclient import TestClient

from core.migrations.runner import run_migrations, utc_now_iso
from core.research.repository import ResearchRepository
from dashboard.app import app
import mcp_server.tools.research_tools as mcp_tools


@pytest.fixture
def api_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_api_mcp.db"
        run_migrations(db_path, create_backup=False)

        # Point singletons to test db
        test_repo = ResearchRepository(db_path)
        from dashboard.routes import research_api
        old_repo = research_api.repo
        research_api.repo = test_repo
        research_api.project_service.repo = test_repo
        research_api.library_service.repo = test_repo
        research_api.annotation_service.repo = test_repo
        research_api.acquisition_service.repo = test_repo
        research_api.interchange_service.repo = test_repo

        old_mcp_repo = mcp_tools.repo
        mcp_tools.repo = test_repo
        mcp_tools.project_service.repo = test_repo
        mcp_tools.library_service.repo = test_repo
        mcp_tools.annotation_service.repo = test_repo
        mcp_tools.acquisition_service.repo = test_repo
        mcp_tools.interchange_service.repo = test_repo

        client = TestClient(app)
        yield client, test_repo

        # Restore
        research_api.repo = old_repo
        mcp_tools.repo = old_mcp_repo


def test_a19_rest_and_mcp_equivalence(api_client):
    """A19: REST y MCP para la misma operación producen el mismo estado persistente."""
    client, repo = api_client

    # 1. Create Project via REST
    resp = client.post("/api/v2/research/projects", json={
        "name": "REST Created Project",
        "description": "Via HTTP",
        "research_type": "SLR",
    })
    assert resp.status_code == 201
    rest_proj = resp.json()
    rest_pid = rest_proj["project_id"]

    # 2. Create Project via MCP Tool
    mcp_proj = mcp_tools.research_create_project(
        name="MCP Created Project",
        description="Via Tool",
        research_type="SLR",
    )
    mcp_pid = mcp_proj["project_id"]

    # Verify both projects exist in DB with identical schema structure
    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM research_projects WHERE project_id = ?", (rest_pid,))
        p1 = cur.fetchone()
        cur.execute("SELECT * FROM research_projects WHERE project_id = ?", (mcp_pid,))
        p2 = cur.fetchone()

        assert p1 is not None and p2 is not None
        assert p1["name"] == "REST Created Project"
        assert p2["name"] == "MCP Created Project"
        assert p1["revision"] == 1 and p2["revision"] == 1

        # Check event logging: REST logs HUMAN actor, MCP logs AGENT actor
        cur.execute("SELECT actor_type FROM research_events WHERE project_id = ? AND action = 'CREATED'", (rest_pid,))
        assert cur.fetchone()[0] == "HUMAN"
        cur.execute("SELECT actor_type FROM research_events WHERE project_id = ? AND action = 'CREATED'", (mcp_pid,))
        assert cur.fetchone()[0] == "AGENT"


def test_uniform_error_responses(api_client):
    client, _ = api_client

    # 404 NOT_FOUND
    r404 = client.get("/api/v2/research/projects/non-existent-uuid")
    assert r404.status_code == 404
    err_body = r404.json()
    assert "error" in err_body
    assert err_body["error"]["code"] == "NOT_FOUND"

    # Create project to test conflict
    p = client.post("/api/v2/research/projects", json={"name": "Conflict Project"}).json()
    pid = p["project_id"]

    # 409 REVISION_CONFLICT
    r409 = client.patch(f"/api/v2/research/projects/{pid}", json={
        "name": "New Name",
        "expected_revision": 999,  # Mismatch!
    })
    assert r409.status_code == 409
    assert r409.json()["error"]["code"] == "REVISION_CONFLICT"


def test_block1_backward_compatibility(api_client):
    """Ensure Block 1 endpoints continue working seamlessly."""
    client, _ = api_client

    r_history = client.get("/api/history")
    assert r_history.status_code == 200
    assert isinstance(r_history.json(), list)

    r_corpus = client.get("/api/corpus/papers?project_id=default_slr")
    assert r_corpus.status_code == 200
    assert "papers" in r_corpus.json()
