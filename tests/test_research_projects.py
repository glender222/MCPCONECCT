import pytest
import tempfile
from pathlib import Path

from core.migrations.runner import run_migrations
from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    RevisionConflictError,
    IdempotencyConflictError,
    ProjectArchivedError,
    QuestionInUseError,
)
from core.research.models import (
    ResearchProjectCreate,
    ResearchProjectUpdate,
    SetOutlineRequest,
    QuestionItem,
    ObjectiveItem,
)
from core.research.projects import ProjectService


@pytest.fixture
def test_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_proj.db"
        run_migrations(db_path, create_backup=False)
        repo = ResearchRepository(db_path)
        yield ProjectService(repo), repo


def test_a01_create_project_name_only(test_service):
    """A01: Crear proyecto solo con nombre: funciona sin PICO, criterios o PRISMA."""
    service, _ = test_service
    req = ResearchProjectCreate(name="Proyecto Simple")
    proj = service.create_project(req)
    assert proj["name"] == "Proyecto Simple"
    assert proj["project_id"] is not None
    assert proj["archived"] is False
    assert proj["revision"] == 1

    fetched = service.get_project(proj["project_id"])
    assert fetched["name"] == "Proyecto Simple"
    assert fetched["revision"] == 1


def test_a10_idempotency_project_creation(test_service):
    """A10: Misma mutación/clave dos veces: un evento y respuesta idéntica; distinto cuerpo: 409."""
    service, repo = test_service
    req1 = ResearchProjectCreate(name="Proyecto Idempotente", idempotency_key="idemp-key-1")
    res1 = service.create_project(req1)

    # Repeating exact same request
    res2 = service.create_project(req1)
    assert res1 == res2

    # Different body with same idempotency key -> 409 conflict
    req_diff = ResearchProjectCreate(name="Nombre Diferente", idempotency_key="idemp-key-1")
    with pytest.raises(IdempotencyConflictError):
        service.create_project(req_diff)


def test_a11_revision_conflict(test_service):
    """A11: Dos ediciones con misma revisión inicial: primera funciona, segunda devuelve conflicto."""
    service, _ = test_service
    proj = service.create_project(ResearchProjectCreate(name="Base Project"))
    pid = proj["project_id"]

    # First update with expected_revision=1
    up1 = ResearchProjectUpdate(name="Updated Once", expected_revision=1)
    res1 = service.update_project(pid, up1)
    assert res1["revision"] == 2
    assert res1["name"] == "Updated Once"

    # Second concurrent update attempting with stale expected_revision=1
    up2 = ResearchProjectUpdate(name="Updated Stale", expected_revision=1)
    with pytest.raises(RevisionConflictError) as exc_info:
        service.update_project(pid, up2)
    assert exc_info.value.code == "REVISION_CONFLICT"


def test_archiving_project_and_read_only(test_service):
    service, _ = test_service
    proj = service.create_project(ResearchProjectCreate(name="To Archive"))
    pid = proj["project_id"]

    # Archive project
    service.update_project(pid, ResearchProjectUpdate(archived=True))
    assert service.get_project(pid)["archived"] is True

    # Mutating archived project should fail with ProjectArchivedError
    with pytest.raises(ProjectArchivedError):
        service.update_project(pid, ResearchProjectUpdate(name="Should Fail"))

    # Unarchiving is allowed
    service.update_project(pid, ResearchProjectUpdate(archived=False))
    assert service.get_project(pid)["archived"] is False


def test_outline_management_and_question_protection(test_service):
    service, repo = test_service
    proj = service.create_project(ResearchProjectCreate(name="Outline Project"))
    pid = proj["project_id"]

    # Set outline
    outline_req = SetOutlineRequest(
        expected_revision=1,
        questions=[
            QuestionItem(question_id="q1", text="What are unlearnable examples?", position=0),
            QuestionItem(text="How to defend against them?", position=1),
        ],
        objectives=[
            ObjectiveItem(text="Analyze perturbation stability", position=0),
        ]
    )
    res = service.set_outline(pid, outline_req)
    assert res["revision"] == 2
    assert len(res["questions"]) == 2
    assert len(res["objectives"]) == 1

    # Simulate an annotation linked to q1
    with repo.get_connection() as conn:
        # Create a dummy publication & membership
        conn.execute("INSERT INTO publications (publication_id, title, normalized_title, created_at, updated_at) VALUES ('pub1', 'T', 't', 'now', 'now')")
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, 'pub1', 'now')", (pid,))
        conn.execute("""
        INSERT INTO annotations (annotation_id, project_id, publication_id, kind, body, source_kind, question_id, created_at, updated_at)
        VALUES ('ann1', ?, 'pub1', 'NOTE', 'Test note', 'NONE', 'q1', 'now', 'now')
        """, (pid,))
        conn.commit()

    # Attempt to replace outline omitting q1 -> must raise QuestionInUseError!
    bad_req = SetOutlineRequest(
        expected_revision=2,
        questions=[
            QuestionItem(text="New Question Only", position=0)
        ],
        objectives=[]
    )
    with pytest.raises(QuestionInUseError):
        service.set_outline(pid, bad_req)
