import pytest
import tempfile
import uuid
from pathlib import Path
from pydantic import ValidationError

from core.migrations.runner import run_migrations, utc_now_iso
from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    RevisionConflictError,
    ScopeValidationError,
)
from core.research.models import (
    ResearchProjectCreate,
    AnnotationKind,
    SourceKind,
    AnnotationCreate,
    AnnotationUpdate,
    SetOutlineRequest,
    QuestionItem,
)
from core.research.projects import ProjectService
from core.research.annotations import AnnotationService


@pytest.fixture
def annot_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_annot.db"
        run_migrations(db_path, create_backup=False)
        repo = ResearchRepository(db_path)
        proj_service = ProjectService(repo)
        annot_service = AnnotationService(repo)
        yield annot_service, proj_service, repo


def test_a08_abstract_evidence_rules(annot_env):
    """A08: Abstract usado como evidencia: etiqueta ABSTRACT en UI y exportación; no FULLTEXT. locator debe ser null."""
    annot_service, proj_service, repo = annot_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Evidence Project"))
    pid = proj["project_id"]
    now = utc_now_iso()

    pub_id = str(uuid.uuid4())
    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, title, normalized_title, created_at, updated_at) VALUES (?, 'Title', 'title', ?, ?)", (pub_id, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (pid, pub_id, now))
        conn.commit()

    # Valid ABSTRACT evidence: locator is None
    req_abstract = AnnotationCreate(
        publication_id=pub_id,
        kind=AnnotationKind.QUOTE,
        body="Unlearnable examples mislead training via low-level noise.",
        source_kind=SourceKind.ABSTRACT,
        locator=None,
    )
    ann = annot_service.create_annotation(pid, req_abstract)
    assert ann["source_kind"] == "ABSTRACT"
    assert ann["locator"] is None
    assert ann["provenance_badge"] == "Basado en resumen"

    # Invalid ABSTRACT evidence: providing a locator must fail Pydantic model validation!
    with pytest.raises(ValidationError):
        AnnotationCreate(
            publication_id=pub_id,
            kind=AnnotationKind.QUOTE,
            body="Invalid abstract quote",
            source_kind=SourceKind.ABSTRACT,
            locator="p. 12",
        )


def test_fulltext_evidence_requires_locator(annot_env):
    annot_service, proj_service, repo = annot_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Fulltext Project"))
    pid = proj["project_id"]
    now = utc_now_iso()

    pub_id = str(uuid.uuid4())
    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, title, normalized_title, created_at, updated_at) VALUES (?, 'Title', 'title', ?, ?)", (pub_id, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (pid, pub_id, now))
        conn.commit()

    # FULLTEXT without locator must fail validation
    with pytest.raises(ValidationError):
        AnnotationCreate(
            publication_id=pub_id,
            kind=AnnotationKind.PARAPHRASE,
            body="Paraphrased finding",
            source_kind=SourceKind.FULLTEXT,
            locator=None,
        )

    # Valid FULLTEXT evidence with locator
    req_full = AnnotationCreate(
        publication_id=pub_id,
        kind=AnnotationKind.PARAPHRASE,
        body="Paraphrased finding from section 3.2",
        source_kind=SourceKind.FULLTEXT,
        locator="p. 7, sección 3.2",
    )
    ann = annot_service.create_annotation(pid, req_full)
    assert ann["source_kind"] == "FULLTEXT"
    assert ann["locator"] == "p. 7, sección 3.2"
    assert "Texto completo: p. 7, sección 3.2" in ann["provenance_badge"]


def test_a09_question_from_another_project_raises_scope_error(annot_env):
    """A09: Asignar pregunta de otro proyecto: error, cero escrituras parciales."""
    annot_service, proj_service, repo = annot_env
    p1 = proj_service.create_project(ResearchProjectCreate(name="Project 1"))
    p2 = proj_service.create_project(ResearchProjectCreate(name="Project 2"))
    p1_id, p2_id = p1["project_id"], p2["project_id"]
    now = utc_now_iso()

    # Add question to Project 2
    proj_service.set_outline(p2_id, SetOutlineRequest(
        expected_revision=1,
        questions=[QuestionItem(question_id="q_in_p2", text="Question in Project 2", position=0)]
    ))

    # Add publication to Project 1
    pub_in_p1 = str(uuid.uuid4())
    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, title, normalized_title, created_at, updated_at) VALUES (?, 'Title', 'title', ?, ?)", (pub_in_p1, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (p1_id, pub_in_p1, now))
        conn.commit()

    # Attempt to link an annotation in Project 1 to q_in_p2 (from Project 2)
    req = AnnotationCreate(
        publication_id=pub_in_p1,
        kind=AnnotationKind.NOTE,
        body="Note trying to hijack foreign question",
        source_kind=SourceKind.NONE,
        question_id="q_in_p2",
    )
    with pytest.raises(ScopeValidationError) as exc:
        annot_service.create_annotation(p1_id, req)
    assert "does not belong to project" in exc.value.message

    # Ensure zero annotations written in Project 1
    annots = annot_service.list_annotations(p1_id)
    assert annots["total"] == 0


def test_update_annotation_revisions_and_events(annot_env):
    annot_service, proj_service, repo = annot_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Annot Updates"))
    pid = proj["project_id"]
    now = utc_now_iso()

    pub_id = str(uuid.uuid4())
    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, title, normalized_title, created_at, updated_at) VALUES (?, 'T', 't', ?, ?)", (pub_id, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (pid, pub_id, now))
        conn.commit()

    ann = annot_service.create_annotation(pid, AnnotationCreate(
        publication_id=pub_id,
        kind=AnnotationKind.NOTE,
        body="Initial body",
        source_kind=SourceKind.NONE,
    ))
    ann_id = ann["annotation_id"]
    assert ann["revision"] == 1

    # Update with expected_revision=1
    updated = annot_service.update_annotation(pid, ann_id, AnnotationUpdate(
        body="Revised body",
        expected_revision=1,
    ))
    assert updated["body"] == "Revised body"
    assert updated["revision"] == 2

    # Second update with stale revision=1 must raise RevisionConflictError
    with pytest.raises(RevisionConflictError):
        annot_service.update_annotation(pid, ann_id, AnnotationUpdate(
            body="Stale update",
            expected_revision=1,
        ))
