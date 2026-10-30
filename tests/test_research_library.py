import pytest
import tempfile
import uuid
from pathlib import Path

from core.migrations.runner import run_migrations, utc_now_iso
from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    RevisionConflictError,
    ScopeValidationError,
)
from core.research.models import (
    ResearchProjectCreate,
    UpdateReadingStatusRequest,
    ReadingStatus,
    SetOrganizationRequest,
    CollectionDefinition,
    TagDefinition,
    CollectionAssignment,
    TagAssignment,
    MergePublicationsRequest,
)
from core.research.projects import ProjectService
from core.research.library import LibraryService


@pytest.fixture
def library_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_lib.db"
        run_migrations(db_path, create_backup=False)
        repo = ResearchRepository(db_path)
        proj_service = ProjectService(repo)
        lib_service = LibraryService(repo)
        yield lib_service, proj_service, repo


def test_a02_same_doi_in_two_projects_isolated_memberships(library_env):
    """A02: Mismo DOI en proyectos A/B: una publicación, dos pertenencias; cambiar lectura en A no cambia B."""
    lib_service, proj_service, repo = library_env

    # Create Project A and Project B
    proj_a = proj_service.create_project(ResearchProjectCreate(name="Project A"))
    proj_b = proj_service.create_project(ResearchProjectCreate(name="Project B"))
    pa_id = proj_a["project_id"]
    pb_id = proj_b["project_id"]

    # Insert single publication with DOI
    pub_id = str(uuid.uuid4())
    now = utc_now_iso()
    with repo.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at)
            VALUES (?, '10.1109/test.doi.1', 'Robust Unlearnable Examples', 'robust unlearnable examples', ?, ?)
            """,
            (pub_id, now, now),
        )
        # Add to both projects as UNREAD
        conn.execute(
            "INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'UNREAD', ?)",
            (pa_id, pub_id, now),
        )
        conn.execute(
            "INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'UNREAD', ?)",
            (pb_id, pub_id, now),
        )
        conn.commit()

    # Verify only 1 global publication exists
    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM publications WHERE doi = '10.1109/test.doi.1'")
        assert cur.fetchone()[0] == 1

    # In Project A: change reading status to READ
    lib_service.update_reading_status(pa_id, pub_id, UpdateReadingStatusRequest(reading_status=ReadingStatus.READ))

    # Verify status in Project A is READ
    pub_in_a = lib_service.get_publication(pa_id, pub_id)
    assert pub_in_a["reading_status"] == "READ"

    # Verify status in Project B is STILL UNREAD
    pub_in_b = lib_service.get_publication(pb_id, pub_id)
    assert pub_in_b["reading_status"] == "UNREAD"


def test_a05_similar_titles_different_dois_remain_separated(library_env):
    """A05: Títulos similares y DOI distintos: permanecen separados."""
    lib_service, proj_service, repo = library_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Deduplication Project"))
    pid = proj["project_id"]
    now = utc_now_iso()

    pub1 = str(uuid.uuid4())
    pub2 = str(uuid.uuid4())

    with repo.get_connection() as conn:
        conn.execute(
            "INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.1001/a', 'Image Cloaking Defense', 'image cloaking defense', ?, ?)",
            (pub1, now, now),
        )
        conn.execute(
            "INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.1002/b', 'Image Cloaking Defenses', 'image cloaking defenses', ?, ?)",
            (pub2, now, now),
        )
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (pid, pub1, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (pid, pub2, now))
        conn.commit()

    pubs = lib_service.list_publications(pid)
    assert pubs["total"] == 2
    pub_ids = {p["publication_id"] for p in pubs["items"]}
    assert pub_ids == {pub1, pub2}


def test_a07_manual_merge_publications(library_env):
    """A07: Fusión manual con notas/colecciones en ambos lados: todas las relaciones sobreviven y alias resuelve al superviviente."""
    lib_service, proj_service, repo = library_env
    proj = proj_service.create_project(ResearchProjectCreate(name="Merge Project"))
    pid = proj["project_id"]
    now = utc_now_iso()

    survivor_id = str(uuid.uuid4())
    absorbed_id = str(uuid.uuid4())
    coll_id = str(uuid.uuid4())
    tag_id = str(uuid.uuid4())

    with repo.get_connection() as conn:
        conn.execute(
            "INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.1111/surv', 'Survivor Study', 'survivor study', ?, ?)",
            (survivor_id, now, now),
        )
        conn.execute(
            "INSERT INTO publications (publication_id, doi, title, normalized_title, created_at, updated_at) VALUES (?, '10.2222/abs', 'Absorbed Study', 'absorbed study', ?, ?)",
            (absorbed_id, now, now),
        )
        # Survivor is READING, Absorbed is READ -> result should be READ
        conn.execute("INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'READING', ?)", (pid, survivor_id, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, reading_status, added_at) VALUES (?, ?, 'READ', ?)", (pid, absorbed_id, now))

        # Collection on survivor, Tag on absorbed
        conn.execute("INSERT INTO collections (collection_id, project_id, name, name_key) VALUES (?, ?, 'Core Methods', 'core methods')", (coll_id, pid))
        conn.execute("INSERT INTO collection_members (collection_id, project_id, publication_id) VALUES (?, ?, ?)", (coll_id, pid, survivor_id))

        conn.execute("INSERT INTO tags (tag_id, project_id, name, name_key) VALUES (?, ?, 'Adversarial', 'adversarial')", (tag_id, pid))
        conn.execute("INSERT INTO publication_tags (tag_id, project_id, publication_id) VALUES (?, ?, ?)", (tag_id, pid, absorbed_id))

        # Annotations on both sides
        conn.execute("""
        INSERT INTO annotations (annotation_id, project_id, publication_id, kind, body, source_kind, created_at, updated_at)
        VALUES ('ann_surv', ?, ?, 'NOTE', 'Note on survivor', 'NONE', ?, ?)
        """, (pid, survivor_id, now, now))
        conn.execute("""
        INSERT INTO annotations (annotation_id, project_id, publication_id, kind, body, source_kind, created_at, updated_at)
        VALUES ('ann_abs', ?, ?, 'NOTE', 'Note on absorbed', 'NONE', ?, ?)
        """, (pid, absorbed_id, now, now))

        conn.commit()

    # Execute manual merge
    merge_req = MergePublicationsRequest(survivor_id=survivor_id, absorbed_id=absorbed_id)
    res = lib_service.merge_publications(pid, merge_req)
    assert res["final_reading_status"] == "READ"
    assert res["survivor_id"] == survivor_id

    # Verify alias exists
    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT publication_id, alias_type FROM publication_aliases WHERE old_id = ?", (absorbed_id,))
        alias = cur.fetchone()
        assert alias is not None
        assert alias["publication_id"] == survivor_id
        assert alias["alias_type"] == "MERGED"

        # Absorbed publication was deleted from publications table
        cur.execute("SELECT 1 FROM publications WHERE publication_id = ?", (absorbed_id,))
        assert cur.fetchone() is None

        # Survivor inherited the tag from absorbed
        cur.execute("SELECT tag_id FROM publication_tags WHERE publication_id = ?", (survivor_id,))
        assert cur.fetchone()["tag_id"] == tag_id

        # Survivor kept its collection
        cur.execute("SELECT collection_id FROM collection_members WHERE publication_id = ?", (survivor_id,))
        assert cur.fetchone()["collection_id"] == coll_id

        # Both annotations now point to survivor_id
        cur.execute("SELECT COUNT(*) FROM annotations WHERE publication_id = ?", (survivor_id,))
        assert cur.fetchone()[0] == 2

    # Querying absorbed_id resolves to survivor via alias
    resolved_pub = lib_service.get_publication(pid, absorbed_id)
    assert resolved_pub["publication_id"] == survivor_id


def test_a09_organization_scope_validation_error(library_env):
    """A09: Asignar etiqueta/colección de otro proyecto: error, cero escrituras parciales."""
    lib_service, proj_service, repo = library_env
    p1 = proj_service.create_project(ResearchProjectCreate(name="Project 1"))
    p2 = proj_service.create_project(ResearchProjectCreate(name="Project 2"))
    p1_id = p1["project_id"]
    p2_id = p2["project_id"]
    now = utc_now_iso()

    pub_in_p2 = str(uuid.uuid4())
    with repo.get_connection() as conn:
        conn.execute("INSERT INTO publications (publication_id, title, normalized_title, created_at, updated_at) VALUES (?, 'T2', 't2', ?, ?)", (pub_in_p2, now, now))
        conn.execute("INSERT INTO project_publications (project_id, publication_id, added_at) VALUES (?, ?, ?)", (p2_id, pub_in_p2, now))
        conn.commit()

    # Attempt to assign pub_in_p2 (from Project 2) to a collection in Project 1
    req = SetOrganizationRequest(
        expected_revision=1,
        collections=[CollectionDefinition(collection_id="c1", name="Methods")],
        collection_members=[CollectionAssignment(collection_id="c1", publication_id=pub_in_p2)],
    )
    with pytest.raises(ScopeValidationError) as exc:
        lib_service.set_organization(p1_id, req)
    assert "does not belong to project" in exc.value.message

    # Verify zero partial writes in p1
    org = lib_service.get_organization(p1_id)
    assert len(org["collections"]) == 0
    assert len(org["collection_members"]) == 0
