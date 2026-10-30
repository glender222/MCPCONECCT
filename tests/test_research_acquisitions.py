import pytest
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.migrations.runner import run_migrations, utc_now_iso
from core.research.repository import ResearchRepository
from core.research.models import ResearchProjectCreate, StartSearchRequest
from core.research.projects import ProjectService
from core.research.acquisitions import AcquisitionService


@pytest.fixture
def acq_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_acq.db"
        run_migrations(db_path, create_backup=False)
        repo = ResearchRepository(db_path)
        proj_service = ProjectService(repo)
        acq_service = AcquisitionService(repo)
        yield acq_service, proj_service, repo


def test_a03_repeat_page_with_same_run_id(acq_env):
    """A03: Repetir una página con mismo run: conteos y anotaciones permanecen iguales."""
    acq_service, proj_service, repo = acq_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Acq Project"))
    pid = proj["project_id"]
    run_id = str(uuid.uuid4())
    now = utc_now_iso()

    with repo.get_connection() as conn:
        conn.execute("INSERT INTO acquisition_runs (run_id, project_id, kind, status, started_at) VALUES (?, ?, 'SEARCH', 'RUNNING', ?)", (run_id, pid, now))
        conn.commit()

    sample_papers = [
        {"doi": "10.1109/test.1", "title": "Paper 1", "authors": ["Author A"], "year": 2024},
        {"doi": "10.1109/test.2", "title": "Paper 2", "authors": ["Author B"], "year": 2024},
    ]

    # Ingest first time
    with repo.get_connection() as conn:
        added_1 = acq_service.ingest_batch_of_papers(conn, pid, run_id, sample_papers)
        conn.commit()
    assert added_1 == 2

    # Ingest second time with exact same run_id (repeating page)
    with repo.get_connection() as conn:
        added_2 = acq_service.ingest_batch_of_papers(conn, pid, run_id, sample_papers)
        conn.commit()
    assert added_2 == 0  # Zero new observations added!

    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM source_observations WHERE run_id = ?", (run_id,))
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT COUNT(*) FROM publications")
        assert cur.fetchone()[0] == 2


def test_a04_new_search_same_doi_adds_observation_not_duplicate_publication(acq_env):
    """A04: Nueva búsqueda del mismo DOI: nueva observación, ninguna publicación duplicada."""
    acq_service, proj_service, repo = acq_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Multi Search Project"))
    pid = proj["project_id"]
    run1 = str(uuid.uuid4())
    run2 = str(uuid.uuid4())
    now = utc_now_iso()

    with repo.get_connection() as conn:
        conn.execute("INSERT INTO acquisition_runs (run_id, project_id, kind, status, started_at) VALUES (?, ?, 'SEARCH', 'RUNNING', ?)", (run1, pid, now))
        conn.execute("INSERT INTO acquisition_runs (run_id, project_id, kind, status, started_at) VALUES (?, ?, 'SEARCH', 'RUNNING', ?)", (run2, pid, now))
        conn.commit()

    paper = [{"doi": "10.1109/identical.doi", "title": "Identical Paper", "authors": ["A. Kot"], "year": 2024}]

    # Ingest under run 1
    with repo.get_connection() as conn:
        acq_service.ingest_batch_of_papers(conn, pid, run1, paper)
        conn.commit()

    # Ingest under run 2
    with repo.get_connection() as conn:
        acq_service.ingest_batch_of_papers(conn, pid, run2, paper)
        conn.commit()

    with repo.get_connection() as conn:
        cur = conn.cursor()
        # Exactly 1 global publication
        cur.execute("SELECT COUNT(*) FROM publications WHERE doi = '10.1109/identical.doi'")
        assert cur.fetchone()[0] == 1
        # Exactly 2 observations (one for each search run)
        cur.execute("SELECT COUNT(*) FROM source_observations")
        assert cur.fetchone()[0] == 2


def test_a12_limit_reached_sets_partial_and_limit_stop_reason(acq_env):
    """A12: Conector anuncia 1000 y límite descarga 100: reported_total=1000, observed_count=100, status=PARTIAL."""
    acq_service, proj_service, _ = acq_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Limit Project"))
    pid = proj["project_id"]

    mock_platform = MagicMock()
    # Generates 25 papers per page, reported total 1000
    mock_platform.search.side_effect = lambda **kwargs: {
        "total_results": 1000,
        "page": kwargs.get("page", 1),
        "page_size": 25,
        "papers": [
            {"doi": f"10.1000/{kwargs.get('page')}_{i}", "title": f"Paper {kwargs.get('page')}_{i}", "authors": ["Auth"]}
            for i in range(25)
        ]
    }

    with patch("platforms.get_platform", return_value=mock_platform):
        req = StartSearchRequest(
            database="ieee",
            query="unlearnable",
            max_records=50,  # Limit to 50
        )
        res = acq_service.start_search(pid, req, run_in_background=False)
        run_data = acq_service.get_run(pid, res["run_id"])

        assert run_data["status"] == "PARTIAL"
        assert run_data["stop_reason"] == "LIMIT"
        assert run_data["reported_total"] == 1000
        assert run_data["observed_count"] == 50
        assert run_data["unique_count"] == 50


def test_a13_waf_after_one_page_preserves_page_and_sets_waf_stop_reason(acq_env):
    """A13: WAF después de una página: página conservada y run PARTIAL/WAF."""
    acq_service, proj_service, repo = acq_env
    proj = proj_service.create_project(ResearchProjectCreate(name="WAF Project"))
    pid = proj["project_id"]

    call_count = 0
    def mock_search(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "total_results": 500,
                "papers": [{"doi": f"10.1000/waf_{i}", "title": f"P {i}", "authors": ["A"]} for i in range(25)]
            }
        raise Exception("403 Forbidden Cloudflare WAF detected")

    mock_platform = MagicMock()
    mock_platform.search.side_effect = mock_search

    with patch("platforms.get_platform", return_value=mock_platform):
        req = StartSearchRequest(database="scopus", query="waf test", max_records=50)
        res = acq_service.start_search(pid, req, run_in_background=False)
        run_data = acq_service.get_run(pid, res["run_id"])

        assert run_data["status"] == "PARTIAL"
        assert run_data["stop_reason"] == "WAF"
        assert run_data["observed_count"] == 25

        # Verify papers from page 1 were preserved in database!
        with repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM publications WHERE doi LIKE '10.1000/waf_%'")
            assert cur.fetchone()[0] == 25
