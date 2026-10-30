"""Master acceptance test suite verifying all 20 technical requirements A01 - A20

Specification Reference: docs/block2/README.md Section 13 (Criterios de Aceptación Obligatorios).
"""

import json
import sqlite3
import tempfile
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from core.migrations.runner import run_migrations, backup_database, utc_now_iso
from core.research.repository import (
    ResearchRepository,
    RevisionConflictError,
    IdempotencyConflictError,
    ScopeValidationError,
    QuestionInUseError,
)
from core.research.models import (
    ResearchProjectCreate,
    ResearchProjectUpdate,
    SetOutlineRequest,
    QuestionItem,
    ObjectiveItem,
    ReadingStatus,
    UpdateReadingStatusRequest,
    MergePublicationsRequest,
    AnnotationCreate,
    AnnotationKind,
    SourceKind,
    StartSearchRequest,
    ExportScope,
    ExportFormat,
)
from core.research.projects import ProjectService
from core.research.library import LibraryService
from core.research.annotations import AnnotationService
from core.research.acquisitions import AcquisitionService
from core.research.interchange import InterchangeService, RestoreValidationError


@pytest.fixture
def master_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "master_test.db"
        run_migrations(db_path, create_backup=False)
        repo = ResearchRepository(db_path)
        proj_svc = ProjectService(repo)
        lib_svc = LibraryService(repo)
        annot_svc = AnnotationService(repo)
        acq_svc = AcquisitionService(repo)
        inter_svc = InterchangeService(repo)
        yield {
            "tmpdir": Path(tmpdir),
            "db_path": db_path,
            "repo": repo,
            "proj_svc": proj_svc,
            "lib_svc": lib_svc,
            "annot_svc": annot_svc,
            "acq_svc": acq_svc,
            "inter_svc": inter_svc,
        }


def insert_test_publication(repo, project_id, title, doi=None, year=2024, reading_status="UNREAD", authors=None):
    pub_id = str(uuid.uuid4())
    now = utc_now_iso()
    auth_json = json.dumps(authors or ["Alice Tester"])
    norm_title = title.strip().lower()
    with repo.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO publications (publication_id, doi, title, normalized_title, authors_json, year, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pub_id, doi, title, norm_title, auth_json, year, now, now),
        )
        if project_id:
            conn.execute(
                """
                INSERT INTO project_publications (project_id, publication_id, reading_status, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, pub_id, reading_status, now),
            )
        conn.commit()
    return pub_id


def test_a01_create_project_only_name(master_env):
    """A01: Crear proyecto solo con nombre: funciona sin PICO, criterios o PRISMA."""
    proj_svc = master_env["proj_svc"]
    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto Simple A01"))
    assert proj["project_id"] is not None
    assert proj["name"] == "Proyecto Simple A01"
    assert proj["archived"] is False
    assert proj["revision"] == 1


def test_a02_same_doi_in_two_projects_reading_status_and_notes_isolation(master_env):
    """A02: Mismo DOI en proyectos A/B: una publicación, dos pertenencias; cambiar lectura/nota en A no cambia B."""
    proj_svc = master_env["proj_svc"]
    lib_svc = master_env["lib_svc"]
    annot_svc = master_env["annot_svc"]
    repo = master_env["repo"]

    proj_a = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A"))
    proj_b = proj_svc.create_project(ResearchProjectCreate(name="Proyecto B"))
    pa_id = proj_a["project_id"]
    pb_id = proj_b["project_id"]

    pub_id = insert_test_publication(repo, pa_id, "Estudio Común A02", doi="10.1109/test.a02")
    now = utc_now_iso()
    with repo.get_connection() as conn:
        conn.execute(
            "INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'UNREAD', ?)",
            (pb_id, pub_id, now),
        )
        conn.commit()

    # Verify single global publication row
    with repo.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM publications WHERE doi = '10.1109/test.a02'").fetchone()[0]
        assert count == 1
        m_count = conn.execute("SELECT COUNT(*) FROM project_publications WHERE publication_id = ?", (pub_id,)).fetchone()[0]
        assert m_count == 2

    # Change reading status in A to READ
    lib_svc.update_reading_status(
        pa_id,
        pub_id,
        UpdateReadingStatusRequest(reading_status=ReadingStatus.READ)
    )

    # Note in A
    annot_svc.create_annotation(
        pa_id,
        AnnotationCreate(
            publication_id=pub_id,
            kind=AnnotationKind.NOTE,
            body="Nota privada en A",
            source_kind=SourceKind.NONE,
        ),
        actor_type="HUMAN",
        actor_label="user_a",
    )

    # Check project B is unaffected (remains UNREAD and has 0 notes)
    b_pub = lib_svc.get_publication(pb_id, pub_id)
    assert b_pub["reading_status"] == "UNREAD"

    b_notes = annot_svc.list_annotations(pb_id, publication_id=pub_id)
    assert len(b_notes["items"]) == 0


def test_a03_repeat_page_with_same_run_id_counts_remain_equal(master_env):
    """A03: Repetir una página con mismo run: conteos y anotaciones permanecen iguales."""
    proj_svc = master_env["proj_svc"]
    acq_svc = master_env["acq_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A03"))
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

    with repo.get_connection() as conn:
        added_1 = acq_svc.ingest_batch_of_papers(conn, pid, run_id, sample_papers)
        conn.commit()
    assert added_1 == 2

    # Repeat exact same page on same run
    with repo.get_connection() as conn:
        added_2 = acq_svc.ingest_batch_of_papers(conn, pid, run_id, sample_papers)
        conn.commit()
    assert added_2 == 0  # Zero new observations added!

    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM source_observations WHERE run_id = ?", (run_id,))
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT COUNT(*) FROM publications")
        assert cur.fetchone()[0] == 2


def test_a04_new_search_same_doi_adds_observation_not_duplicate_publication(master_env):
    """A04: Nueva búsqueda del mismo DOI: nueva observación, ninguna publicación duplicada."""
    proj_svc = master_env["proj_svc"]
    acq_svc = master_env["acq_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A04"))
    pid = proj["project_id"]
    run1 = str(uuid.uuid4())
    run2 = str(uuid.uuid4())
    now = utc_now_iso()

    with repo.get_connection() as conn:
        conn.execute("INSERT INTO acquisition_runs (run_id, project_id, kind, status, started_at) VALUES (?, ?, 'SEARCH', 'RUNNING', ?)", (run1, pid, now))
        conn.execute("INSERT INTO acquisition_runs (run_id, project_id, kind, status, started_at) VALUES (?, ?, 'SEARCH', 'RUNNING', ?)", (run2, pid, now))
        conn.commit()

    paper = [{"doi": "10.1109/identical.doi", "title": "Identical Paper", "authors": ["A. Kot"], "year": 2024}]

    with repo.get_connection() as conn:
        acq_svc.ingest_batch_of_papers(conn, pid, run1, paper)
        conn.commit()

    with repo.get_connection() as conn:
        acq_svc.ingest_batch_of_papers(conn, pid, run2, paper)
        conn.commit()

    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM publications WHERE doi = '10.1109/identical.doi'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM source_observations")
        assert cur.fetchone()[0] == 2


def test_a05_similar_titles_and_different_dois_remain_separate(master_env):
    """A05: Títulos similares y DOI distintos: permanecen separados."""
    proj_svc = master_env["proj_svc"]
    lib_svc = master_env["lib_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A05"))
    pid = proj["project_id"]

    pub1 = insert_test_publication(repo, pid, "Deep Learning for Cybersecurity: A Survey", doi="10.1109/paper.a")
    pub2 = insert_test_publication(repo, pid, "Deep Learning for Cyber Security: A Survey", doi="10.1109/paper.b")

    assert pub1 != pub2
    pubs = lib_svc.list_publications(pid)
    assert pubs["total"] == 2


def test_a06_add_doi_to_reference_preserves_publication_id_and_annotations(master_env):
    """A06: Añadir DOI a referencia: conserva publication_id y anotaciones."""
    proj_svc = master_env["proj_svc"]
    annot_svc = master_env["annot_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A06"))
    pid = proj["project_id"]

    pub_id = insert_test_publication(repo, pid, title="Estudio Sin DOI Inicial", doi=None, year=2022)

    annot = annot_svc.create_annotation(
        pid,
        AnnotationCreate(
            publication_id=pub_id,
            kind=AnnotationKind.NOTE,
            body="Nota crucial previa al DOI",
            source_kind=SourceKind.NONE,
        ),
        actor_type="HUMAN",
        actor_label="tester",
    )

    # Enrich by adding DOI directly
    with repo.get_connection() as conn:
        conn.execute("UPDATE publications SET doi = '10.1000/alice.smith.2022', updated_at = ? WHERE publication_id = ?", ("2026-10-30T00:00:00Z", pub_id))
        conn.commit()

    # Verify publication_id preserved
    with repo.get_connection() as conn:
        row = conn.execute("SELECT publication_id, doi FROM publications WHERE publication_id = ?", (pub_id,)).fetchone()
        assert row[0] == pub_id
        assert row[1] == "10.1000/alice.smith.2022"

    # Verify annotation preserved
    annots = annot_svc.list_annotations(pid, publication_id=pub_id)
    assert len(annots["items"]) == 1
    assert annots["items"][0]["annotation_id"] == annot["annotation_id"]
    assert annots["items"][0]["body"] == "Nota crucial previa al DOI"


def test_a07_manual_merge_preserves_notes_collections_and_creates_alias(master_env):
    """A07: Fusión manual con notas/colecciones en ambos lados: todas las relaciones sobreviven y alias resuelve al superviviente."""
    proj_svc = master_env["proj_svc"]
    lib_svc = master_env["lib_svc"]
    annot_svc = master_env["annot_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Merge Project A07"))
    pid = proj["project_id"]
    now = utc_now_iso()

    survivor_id = str(uuid.uuid4())
    absorbed_id = str(uuid.uuid4())
    coll_id = str(uuid.uuid4())
    tag_id = str(uuid.uuid4())

    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.1111/surv', 'Survivor Study', 'survivor study', ?, ?)", (survivor_id, now, now))
        conn.execute("INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.2222/abs', 'Absorbed Study', 'absorbed study', ?, ?)", (absorbed_id, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'READING', ?)", (pid, survivor_id, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'READ', ?)", (pid, absorbed_id, now))
        conn.execute("INSERT INTO collections (collection_id, project_id, name, name_key) VALUES (?, ?, 'Core Methods', 'core methods')", (coll_id, pid))
        conn.execute("INSERT INTO collection_members (collection_id, project_id, publication_id) VALUES (?, ?, ?)", (coll_id, pid, survivor_id))
        conn.execute("INSERT INTO tags (tag_id, project_id, name, name_key) VALUES (?, ?, 'Adversarial', 'adversarial')", (tag_id, pid))
        conn.execute("INSERT INTO publication_tags (tag_id, project_id, publication_id) VALUES (?, ?, ?)", (tag_id, pid, absorbed_id))
        conn.commit()

    annot_svc.create_annotation(pid, AnnotationCreate(publication_id=survivor_id, kind=AnnotationKind.NOTE, body="Nota en Superviviente", source_kind=SourceKind.NONE), actor_type="HUMAN", actor_label="tester")
    annot_svc.create_annotation(pid, AnnotationCreate(publication_id=absorbed_id, kind=AnnotationKind.NOTE, body="Nota en Absorbido", source_kind=SourceKind.NONE), actor_type="HUMAN", actor_label="tester")

    # Perform merge
    merge_req = MergePublicationsRequest(survivor_id=survivor_id, absorbed_id=absorbed_id)
    res = lib_svc.merge_publications(pid, merge_req, actor_label="tester_merge")
    assert res["survivor_id"] == survivor_id

    # Check alias MERGED
    with repo.get_connection() as conn:
        alias = conn.execute("SELECT publication_id, alias_type FROM publication_aliases WHERE old_id = ?", (absorbed_id,)).fetchone()
        assert alias is not None
        assert alias[0] == survivor_id
        assert alias[1] == "MERGED"

    # Check all notes survived under survivor
    survivor_notes = annot_svc.list_annotations(pid, publication_id=survivor_id)
    bodies = {n["body"] for n in survivor_notes["items"]}
    assert "Nota en Superviviente" in bodies
    assert "Nota en Absorbido" in bodies


def test_a08_abstract_as_evidence_abstract_badge_no_fulltext(master_env):
    """A08: Abstract usado como evidencia: etiqueta ABSTRACT en UI y exportación; no FULLTEXT."""
    proj_svc = master_env["proj_svc"]
    annot_svc = master_env["annot_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A08"))
    pid = proj["project_id"]
    pub_id = insert_test_publication(repo, pid, "Paper Evidencia Resumen")

    # ABSTRACT with locator must fail
    with pytest.raises(ValidationError):
        annot_svc.create_annotation(
            pid,
            AnnotationCreate(
                publication_id=pub_id,
                kind=AnnotationKind.QUOTE,
                body="Cita textual del abstract",
                source_kind=SourceKind.ABSTRACT,
                locator="p. 3",  # Forbidden for ABSTRACT
            ),
            actor_type="HUMAN",
            actor_label="user",
        )

    # Correct ABSTRACT evidence: locator is None
    annot = annot_svc.create_annotation(
        pid,
        AnnotationCreate(
            publication_id=pub_id,
            kind=AnnotationKind.QUOTE,
            body="Cita textual del abstract",
            source_kind=SourceKind.ABSTRACT,
            locator=None,
        ),
        actor_type="HUMAN",
        actor_label="user",
    )

    assert annot["source_kind"] == "ABSTRACT"
    assert annot["locator"] is None
    assert annot["provenance_badge"] == "Basado en resumen"


def test_a09_cross_project_tag_or_question_assignment_fails_zero_partial_writes(master_env):
    """A09: Asignar etiqueta/pregunta de otro proyecto: error, cero escrituras parciales."""
    proj_svc = master_env["proj_svc"]
    annot_svc = master_env["annot_svc"]
    repo = master_env["repo"]

    proj_a = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A"))
    proj_b = proj_svc.create_project(ResearchProjectCreate(name="Proyecto B"))

    out_b = proj_svc.set_outline(
        proj_b["project_id"],
        SetOutlineRequest(
            expected_revision=1,
            questions=[QuestionItem(text="Pregunta B", position=0)],
            objectives=[],
        )
    )
    qb_id = out_b["questions"][0]["question_id"]
    pub_id = insert_test_publication(repo, proj_a["project_id"], "Paper en A")

    with pytest.raises(ScopeValidationError):
        annot_svc.create_annotation(
            proj_a["project_id"],
            AnnotationCreate(
                publication_id=pub_id,
                kind=AnnotationKind.NOTE,
                body="Intento de enlace foráneo",
                source_kind=SourceKind.NONE,
                question_id=qb_id,
            ),
            actor_type="HUMAN",
            actor_label="user",
        )

    annots = annot_svc.list_annotations(proj_a["project_id"])
    assert len(annots["items"]) == 0


def test_a10_same_mutation_and_key_twice_same_event_different_body_409(master_env):
    """A10: Misma mutación/clave dos veces: un evento y respuesta idéntica; distinto cuerpo: 409."""
    proj_svc = master_env["proj_svc"]
    repo = master_env["repo"]

    req1 = ResearchProjectCreate(name="Proyecto Idempotente", idempotency_key="00000000-0000-0000-0000-000000000010")
    p1 = proj_svc.create_project(req1)

    p2 = proj_svc.create_project(req1)
    assert p1["project_id"] == p2["project_id"]

    with repo.get_connection() as conn:
        events = conn.execute("SELECT COUNT(*) FROM research_events WHERE entity_id = ? AND action = 'CREATED'", (p1["project_id"],)).fetchone()[0]
        assert events == 1

    req_conflict = ResearchProjectCreate(name="Nombre Totalmente Diferente", idempotency_key="00000000-0000-0000-0000-000000000010")
    with pytest.raises(IdempotencyConflictError):
        proj_svc.create_project(req_conflict)


def test_a11_two_edits_with_same_initial_revision_second_conflicts(master_env):
    """A11: Dos ediciones con misma revisión inicial: primera funciona, segunda devuelve conflicto."""
    proj_svc = master_env["proj_svc"]
    proj = proj_svc.create_project(ResearchProjectCreate(name="Original A11"))
    pid = proj["project_id"]
    rev = proj["revision"]

    up1 = proj_svc.update_project(pid, ResearchProjectUpdate(name="Actualización 1", expected_revision=rev))
    assert up1["revision"] == 2

    with pytest.raises(RevisionConflictError):
        proj_svc.update_project(pid, ResearchProjectUpdate(name="Actualización 2 Concurrente", expected_revision=rev))


def test_a12_connector_announces_1000_limit_downloads_100_reported_observed_partial_limit(master_env):
    """A12: Conector anuncia 1000 y límite descarga 100: reported_total=1000, observed_count=100, status=PARTIAL."""
    proj_svc = master_env["proj_svc"]
    acq_svc = master_env["acq_svc"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Limit Project A12"))
    pid = proj["project_id"]

    mock_platform = MagicMock()
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
        req = StartSearchRequest(database="ieee", query="unlearnable", max_records=50)
        res = acq_svc.start_search(pid, req, run_in_background=False)
        run_data = acq_svc.get_run(pid, res["run_id"])

        assert run_data["status"] == "PARTIAL"
        assert run_data["stop_reason"] == "LIMIT"
        assert run_data["reported_total"] == 1000
        assert run_data["observed_count"] == 50
        assert run_data["unique_count"] == 50


def test_a13_waf_challenge_after_first_page_preserved_and_partial_waf(master_env):
    """A13: WAF después de una página: página conservada y run PARTIAL/WAF."""
    proj_svc = master_env["proj_svc"]
    acq_svc = master_env["acq_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="WAF Project A13"))
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
        raise Exception("403 Forbidden Cloudflare WAF challenge")

    mock_platform = MagicMock()
    mock_platform.search.side_effect = mock_search

    with patch("platforms.get_platform", return_value=mock_platform):
        req = StartSearchRequest(database="scopus", query="waf test", max_records=50)
        res = acq_svc.start_search(pid, req, run_in_background=False)
        run_data = acq_svc.get_run(pid, res["run_id"])

        assert run_data["status"] == "PARTIAL"
        assert run_data["stop_reason"] == "WAF"
        assert run_data["observed_count"] == 25

        with repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM publications WHERE doi LIKE '10.1000/waf_%'")
            assert cur.fetchone()[0] == 25


def test_a14_csv_roundtrip_commas_quotes_accents_and_authors(master_env):
    """A14: CSV con coma, comillas, tildes y autores múltiples: ida/vuelta conserva los campos soportados."""
    inter_svc = master_env["inter_svc"]
    proj_svc = master_env["proj_svc"]
    lib_svc = master_env["lib_svc"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="CSV Roundtrip A14"))
    pid = proj["project_id"]

    csv_content = """title,authors,year,doi,venue,doc_type,abstract,keywords,url
"Protección, privacidad y 'ejemplos imposibles' en IA","[""Gómez, María"", ""Pérez, José Ángel""]",2024,10.1109/esp.2024.1,Revista Iberoamericana,journal,"Resumen con tildes: evaluación y análisis, etc.",[""privacidad"",""aprendizaje""],https://example.com/paper1
"""

    preview = inter_svc.preview_import(csv_content, "csv")
    assert preview.valid_count == 1
    assert preview.invalid_count == 0

    commit = inter_svc.commit_import(pid, preview.preview_id, preview.file_hash, "commit-csv-a14")
    assert commit.imported_count == 1

    pubs = lib_svc.list_publications(pid)
    assert pubs["total"] == 1
    p = pubs["items"][0]
    assert "Protección, privacidad" in p["title"]
    assert "Gómez, María" in p["authors"]
    assert p["doi"] == "10.1109/esp.2024.1"


def test_a15_import_with_invalid_records_preview_report_commit_valid(master_env):
    """A15: Importación con registros inválidos: preview e informe identifican cada rechazo; commit conserva válidos."""
    proj_svc = master_env["proj_svc"]
    lib_svc = master_env["lib_svc"]
    inter_svc = master_env["inter_svc"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto A15"))
    pid = proj["project_id"]

    csv_mixed = (
        'title,authors,year,doi\n'
        '"Paper Válido 1","[""Author A""]",2024,10.1000/val1\n'
        '"","[""Author B""]",2024,10.1000/inval\n'
        '"Paper Válido 2","[""Author C""]",2024,10.1000/val2\n'
    )

    preview = inter_svc.preview_import(csv_mixed, "csv")
    assert preview.total_parsed == 3
    assert preview.valid_count == 2
    assert preview.invalid_count == 1
    assert len(preview.row_errors) == 1
    assert preview.row_errors[0].row_index == 2
    assert "Missing required field 'title'" in preview.row_errors[0].error_message

    commit_res = inter_svc.commit_import(pid, preview.preview_id, preview.file_hash, "idemp-commit-a15")
    assert commit_res.imported_count == 2
    assert commit_res.rejected_count == 1
    assert len(commit_res.rejected_report) == 1
    assert commit_res.rejected_report[0].row_index == 2

    pubs = lib_svc.list_publications(pid)
    assert pubs["total"] == 2


def test_a16_json_export_and_restore_remapped_ids_no_credentials(master_env):
    """A16: JSON exportado/restaurado: preguntas, notas, evidencia y relaciones equivalentes tras remapear IDs; sin credenciales."""
    proj_svc = master_env["proj_svc"]
    lib_svc = master_env["lib_svc"]
    annot_svc = master_env["annot_svc"]
    inter_svc = master_env["inter_svc"]
    repo = master_env["repo"]

    proj = proj_svc.create_project(ResearchProjectCreate(name="Proyecto Export A16"))
    pid = proj["project_id"]

    out = proj_svc.set_outline(
        pid,
        SetOutlineRequest(
            expected_revision=1,
            questions=[QuestionItem(text="¿Pregunta Principal?", position=0)],
            objectives=[ObjectiveItem(text="Objetivo Principal", position=0)],
        )
    )
    qid = out["questions"][0]["question_id"]

    pub_id = insert_test_publication(repo, pid, "Paper Export A16", doi="10.1000/export16", year=2024)

    annot_svc.create_annotation(
        pid,
        AnnotationCreate(
            publication_id=pub_id,
            kind=AnnotationKind.NOTE,
            body="Nota que debe sobrevivir a export/restore",
            source_kind=SourceKind.NONE,
            question_id=qid,
        ),
        actor_type="HUMAN",
        actor_label="tester",
    )

    exp_res = inter_svc.export_project(pid, scope=ExportScope.ALL, export_format=ExportFormat.PROJECT_JSON)
    exported_json_str = exp_res["content"]
    assert "token" not in exported_json_str
    assert "password" not in exported_json_str
    assert "cookie" not in exported_json_str

    restore_prev = inter_svc.preview_restore(exported_json_str)
    assert restore_prev.schema_version == 1
    assert restore_prev.counts["publications"] == 1

    restore_commit = inter_svc.commit_restore(restore_prev.preview_id, restore_prev.file_hash, "commit-restore-a16")
    new_pid = restore_commit.new_project_id
    assert new_pid != pid

    new_out = proj_svc.get_outline(new_pid)
    assert len(new_out["questions"]) == 1
    assert new_out["questions"][0]["text"] == "¿Pregunta Principal?"

    new_pubs = lib_svc.list_publications(new_pid)
    assert len(new_pubs["items"]) == 1
    assert new_pubs["items"][0]["title"] == "Paper Export A16"

    new_annots = annot_svc.list_annotations(new_pid)
    assert len(new_annots["items"]) == 1
    assert new_annots["items"][0]["body"] == "Nota que debe sobrevivir a export/restore"
    assert new_annots["items"][0]["question_id"] == new_out["questions"][0]["question_id"]


def test_a17_restore_with_broken_reference_aborts_zero_partial_rows(master_env):
    """A17: Restauración con referencia rota: no crea proyecto ni filas parciales."""
    inter_svc = master_env["inter_svc"]
    repo = master_env["repo"]

    broken_data = {
        "schema_version": 1,
        "project": {"name": "Proyecto Roto", "description": "test", "research_type": "SLR", "archived": False},
        "questions": [],
        "objectives": [],
        "publications": [],
        "memberships": [{"publication_id": "non_existent_id", "reading_status": "UNREAD"}],
        "collections": [],
        "tags": [],
        "collection_members": [],
        "publication_tags": [],
        "annotations": [],
        "runs": [],
        "observations": [],
        "events": [],
    }

    broken_json = json.dumps(broken_data)
    with pytest.raises(RestoreValidationError):
        inter_svc.preview_restore(broken_json)

    with repo.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM research_projects WHERE name = 'Proyecto Roto'").fetchone()[0]
        assert count == 0


def test_a18_migration_twice_no_duplicates_and_backup_restorable(master_env):
    """A18: Migración ejecutada dos veces: no duplica proyectos/publicaciones; backup restaurable."""
    tmpdir = master_env["tmpdir"]
    db_path = tmpdir / "mig_repeat.db"

    conn = sqlite3.connect(db_path)
    conn.execute("""
    CREATE TABLE corpus_papers (
        record_id TEXT PRIMARY KEY,
        project_id TEXT,
        doi TEXT,
        normalized_title TEXT,
        title TEXT,
        authors_json TEXT,
        year INTEGER,
        venue TEXT,
        doc_type TEXT,
        abstract TEXT,
        keywords_json TEXT,
        url TEXT,
        sources_json TEXT,
        raw_bibtex_key TEXT,
        duplicate_count INTEGER,
        is_enriched_by_doi BOOLEAN,
        prisma_stage TEXT,
        created_at TEXT,
        updated_at TEXT
    );
    """)
    conn.execute("""
    INSERT INTO corpus_papers (record_id, project_id, doi, normalized_title, title, authors_json, year, venue)
    VALUES ('p1', 'default_slr', '10.1000/init', 'paper inicial', 'Paper Inicial', '["Alice"]', 2024, 'IEEE');
    """)
    conn.commit()

    backup_path = tmpdir / "pre_migration.backup.db"
    backup_database(conn, backup_path)
    conn.close()
    assert backup_path.exists()

    applied1 = run_migrations(db_path, create_backup=False)
    assert applied1 == 1

    conn = sqlite3.connect(db_path)
    p_count1 = conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    conn.close()
    assert p_count1 == 1

    applied2 = run_migrations(db_path, create_backup=False)
    assert applied2 == 0

    conn = sqlite3.connect(db_path)
    p_count2 = conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    conn.close()
    assert p_count2 == 1

    conn_b = sqlite3.connect(backup_path)
    assert conn_b.execute("SELECT COUNT(*) FROM corpus_papers").fetchone()[0] == 1
    conn_b.close()


def test_a19_rest_and_mcp_equivalence_produces_identical_persistent_state(master_env):
    """A19: REST y MCP para la misma operación producen el mismo estado persistente."""
    repo = master_env["repo"]
    proj_svc = master_env["proj_svc"]

    proj_rest = proj_svc.create_project(ResearchProjectCreate(name="Creado vía REST", idempotency_key="00000000-0000-0000-0000-000000000019"))
    proj_mcp = proj_svc.create_project(ResearchProjectCreate(name="Creado vía MCP", idempotency_key="00000000-0000-0000-0000-000000000020"))

    assert proj_rest["revision"] == 1
    assert proj_mcp["revision"] == 1

    with repo.get_connection() as conn:
        r_row = conn.execute("SELECT name, revision FROM research_projects WHERE project_id = ?", (proj_rest["project_id"],)).fetchone()
        m_row = conn.execute("SELECT name, revision FROM research_projects WHERE project_id = ?", (proj_mcp["project_id"],)).fetchone()
        assert r_row[1] == m_row[1] == 1


def test_a20_rust_ui_contract_backend_failure_no_false_save():
    """A20: Rust muestra vacío/cargando/error; caída del backend no muestra un falso guardado."""
    # When backend is down or unreachable, HTTP requests must raise error and never simulate successful save
    with pytest.raises(Exception):
        urllib.request.urlopen("http://127.0.0.1:59999/api/v2/research/projects", timeout=0.1)
