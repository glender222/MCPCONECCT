import pytest
import tempfile
import json
import uuid
from pathlib import Path

from core.migrations.runner import run_migrations, utc_now_iso
from core.research.repository import ResearchRepository
from core.research.models import (
    ResearchProjectCreate,
    ExportScope,
    ExportFormat,
    SetOutlineRequest,
    QuestionItem,
    AnnotationCreate,
    AnnotationKind,
    SourceKind,
)
from core.research.projects import ProjectService
from core.research.library import LibraryService
from core.research.annotations import AnnotationService
from core.research.interchange import (
    InterchangeService,
    RestoreValidationError,
    PreviewExpiredOrChangedError,
)


@pytest.fixture
def interchange_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_interchange.db"
        run_migrations(db_path, create_backup=False)
        repo = ResearchRepository(db_path)
        proj_service = ProjectService(repo)
        lib_service = LibraryService(repo)
        annot_service = AnnotationService(repo)
        inter_service = InterchangeService(repo)
        yield inter_service, proj_service, lib_service, annot_service, repo


def test_a14_csv_import_export_roundtrip(interchange_env):
    """A14: CSV con coma, comillas, tildes y autores múltiples: ida/vuelta conserva los campos soportados."""
    inter_service, proj_service, lib_service, _, repo = interchange_env
    proj = proj_service.create_project(ResearchProjectCreate(name="CSV Roundtrip"))
    pid = proj["project_id"]

    # CSV with accents, commas inside quotes, multiple authors
    csv_content = """title,authors,year,doi,venue,doc_type,abstract,keywords,url
"Protección, privacidad y 'ejemplos imposibles' en IA","[""Gómez, María"", ""Pérez, José Ángel""]",2024,10.1109/esp.2024.1,Revista Iberoamericana,journal,"Resumen con tildes: evaluación y análisis, etc.",[""privacidad"",""aprendizaje""],https://example.com/paper1
"""

    # Preview
    preview = inter_service.preview_import(csv_content, "csv")
    assert preview.valid_count == 1
    assert preview.invalid_count == 0

    # Commit
    commit = inter_service.commit_import(pid, preview.preview_id, preview.file_hash, "commit-csv-1")
    assert commit.imported_count == 1
    assert commit.rejected_count == 0

    # Verify publication in library
    pubs = lib_service.list_publications(pid)
    assert pubs["total"] == 1
    p = pubs["items"][0]
    assert p["title"] == "Protección, privacidad y 'ejemplos imposibles' en IA"
    assert len(p["authors"]) == 2
    assert "Pérez, José Ángel" in p["authors"]
    assert p["doi"] == "10.1109/esp.2024.1"

    # Export back to CSV
    exported = inter_service.export_project(pid, ExportScope.ALL, ExportFormat.CSV)
    assert "Protección, privacidad" in exported["content"]
    assert "Pérez, José Ángel" in exported["content"]


def test_a15_import_with_invalid_records_report(interchange_env):
    """A15: Importación con registros inválidos: preview e informe identifican cada rechazo; commit conserva válidos."""
    inter_service, proj_service, lib_service, _, repo = interchange_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Invalid CSV Project"))
    pid = proj["project_id"]

    # Row 1 valid, Row 2 missing title (invalid), Row 3 valid
    csv_content = """title,authors,year,doi
"Valid Paper 1","[""Author One""]",2024,10.1000/1
"","[""Author Two""]",2024,10.1000/2
"Valid Paper 3","[""Author Three""]",2024,10.1000/3
"""

    preview = inter_service.preview_import(csv_content, "csv")
    assert preview.valid_count == 2
    assert preview.invalid_count == 1
    assert len(preview.row_errors) == 1
    assert preview.row_errors[0].row_index == 2
    assert "Missing required field 'title'" in preview.row_errors[0].error_message

    # Commit imports the 2 valid papers and retains rejection report
    commit = inter_service.commit_import(pid, preview.preview_id, preview.file_hash, "commit-csv-inv")
    assert commit.imported_count == 2
    assert commit.rejected_count == 1
    assert len(commit.rejected_report) == 1
    assert commit.rejected_report[0].row_index == 2

    # Check database: 2 papers ingested
    pubs = lib_service.list_publications(pid)
    assert pubs["total"] == 2


def test_a16_export_and_restore_project_json_equivalence(interchange_env):
    """A16: JSON exportado/restaurado: preguntas, notas, evidencia y relaciones equivalentes tras remapear IDs; sin credenciales."""
    inter_service, proj_service, lib_service, annot_service, repo = interchange_env
    proj = proj_service.create_project(ResearchProjectCreate(
        name="Source Project",
        description="Comprehensive testing of project JSON export and restore",
        research_type="SLR"
    ))
    pid = proj["project_id"]

    # Add outline
    proj_service.set_outline(pid, SetOutlineRequest(
        expected_revision=1,
        questions=[QuestionItem(question_id="q1", text="What perturbations are effective?", position=0)],
        objectives=[]
    ))

    # Add a publication
    now = utc_now_iso()
    pub_id = str(uuid.uuid4())
    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.1000/exp1', 'Export Test Paper', 'export test paper', ?, ?)", (pub_id, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'READING', ?)", (pid, pub_id, now))
        conn.commit()

    # Add an evidence annotation linked to q1
    annot = annot_service.create_annotation(pid, AnnotationCreate(
        publication_id=pub_id,
        kind=AnnotationKind.QUOTE,
        body="Crucial finding regarding adversarial feature alignment",
        source_kind=SourceKind.FULLTEXT,
        locator="p. 15, sec 4",
        question_id="q1",
    ))

    # Export project JSON
    export_res = inter_service.export_project(pid, ExportScope.ALL, ExportFormat.PROJECT_JSON)
    json_text = export_res["content"]

    # Verify no sensitive keywords exist in export
    for sensitive in ["api_key", "password", "token", "cookies", "headers"]:
        assert f'"{sensitive}": "' not in json_text

    # Preview Restore
    restore_prev = inter_service.preview_restore(json_text)
    assert restore_prev.schema_version == 1
    assert restore_prev.counts["questions"] == 1
    assert restore_prev.counts["annotations"] == 1
    assert restore_prev.counts["publications"] == 1

    # Commit Restore
    restore_commit = inter_service.commit_restore(
        restore_prev.preview_id, restore_prev.file_hash, "commit-restore-1"
    )
    new_pid = restore_commit.new_project_id
    assert new_pid != pid  # Brand new project created!

    # Verify new project exists and has restored outline, publications and annotations
    new_proj = proj_service.get_project(new_pid)
    assert "Source Project (Restored)" in new_proj["name"]

    new_outline = proj_service.get_outline(new_pid)
    assert len(new_outline["questions"]) == 1
    new_qid = new_outline["questions"][0]["question_id"]
    assert new_qid != "q1"  # ID was cleanly remapped!

    new_pubs = lib_service.list_publications(new_pid)
    assert new_pubs["total"] == 1
    new_pub_item = new_pubs["items"][0]
    assert new_pub_item["doi"] == "10.1000/exp1"

    new_annots = annot_service.list_annotations(new_pid)
    assert new_annots["total"] == 1
    new_ann = new_annots["items"][0]
    assert new_ann["body"] == "Crucial finding regarding adversarial feature alignment"
    assert new_ann["question_id"] == new_qid  # Annotation correctly linked to remapped question!
    assert new_ann["source_kind"] == "FULLTEXT"
    assert new_ann["locator"] == "p. 15, sec 4"


def test_a17_restore_broken_reference_cancels_entire_restoration(interchange_env):
    """A17: Restauración con referencia rota: no crea proyecto ni filas parciales."""
    inter_service, proj_service, _, _, repo = interchange_env

    # Malformed project JSON with annotation referencing non-existent question
    broken_data = {
        "schema_version": 1,
        "project": {"project_id": "orig_p", "name": "Broken Reference Project"},
        "questions": [],
        "publications": [{"publication_id": "p1", "title": "P1", "authors_json": "[]"}],
        "memberships": [{"publication_id": "p1", "reading_status": "UNREAD"}],
        "annotations": [
            {
                "annotation_id": "a1",
                "publication_id": "p1",
                "kind": "NOTE",
                "body": "Note",
                "source_kind": "NONE",
                "question_id": "missing_question_999",  # Broken reference!
            }
        ]
    }

    broken_json = json.dumps(broken_data)
    with pytest.raises(RestoreValidationError) as exc:
        inter_service.preview_restore(broken_json)
    assert "Broken reference" in exc.value.message

    # Ensure no project or publications were created in DB
    projects = proj_service.list_projects()
    for p in projects["items"]:
        assert "Broken Reference Project" not in p["name"]
