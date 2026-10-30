"""
REST API Router for Block 2 Research System (/api/v2/research).
Implements Section 8: Uniform error format, shared services, strict Pydantic models.
"""
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, Query, Header, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from core.research.repository import (
    ResearchRepository,
    ResearchError,
    NotFoundError,
    RevisionConflictError,
    IdempotencyConflictError,
    ProjectArchivedError,
    QuestionInUseError,
    ScopeValidationError,
)
from core.research.models import (
    ResearchProjectCreate,
    ResearchProjectUpdate,
    SetOutlineRequest,
    UpdateReadingStatusRequest,
    SetOrganizationRequest,
    AnnotationCreate,
    AnnotationUpdate,
    StartSearchRequest,
    ImportPreviewRequest,
    ImportCommitRequest,
    ExportProjectRequest,
    RestorePreviewRequest,
    RestoreCommitRequest,
    MergePublicationsRequest,
)
from core.research.projects import ProjectService
from core.research.library import LibraryService
from core.research.annotations import AnnotationService
from core.research.acquisitions import AcquisitionService
from core.research.interchange import InterchangeService

router = APIRouter(prefix="/api/v2/research", tags=["Research V2"])

repo = ResearchRepository()
project_service = ProjectService(repo)
library_service = LibraryService(repo)
annotation_service = AnnotationService(repo)
acquisition_service = AcquisitionService(repo)
interchange_service = InterchangeService(repo)


def format_error_response(code: str, message: str, details: Dict[str, Any] = None, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


# --- Projects ---

@router.post("/projects", status_code=201)
def create_project(req: ResearchProjectCreate, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return project_service.create_project(req, actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.get("/projects")
def list_projects(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), include_archived: bool = True):
    return project_service.list_projects(limit=limit, offset=offset, include_archived=include_archived)


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    try:
        return project_service.get_project(project_id)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.patch("/projects/{project_id}")
def update_project(project_id: str, req: ResearchProjectUpdate, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return project_service.update_project(project_id, req, actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Outline (Questions & Objectives) ---

@router.put("/projects/{project_id}/outline")
def set_outline(project_id: str, req: SetOutlineRequest, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return project_service.set_outline(project_id, req, actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.get("/projects/{project_id}/outline")
def get_outline(project_id: str):
    try:
        return project_service.get_outline(project_id)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Library & Publications ---

@router.get("/projects/{project_id}/publications")
def list_publications(
    project_id: str,
    q: Optional[str] = None,
    reading_status: Optional[str] = None,
    collection_id: Optional[str] = None,
    tag_id: Optional[str] = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        return library_service.list_publications(
            project_id=project_id,
            q=q,
            reading_status=reading_status,
            collection_id=collection_id,
            tag_id=tag_id,
            limit=limit,
            offset=offset,
        )
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.get("/projects/{project_id}/publications/{publication_id}")
def get_publication(project_id: str, publication_id: str):
    try:
        return library_service.get_publication(project_id, publication_id)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.patch("/projects/{project_id}/publications/{publication_id}")
def update_reading_status(
    project_id: str, publication_id: str, req: UpdateReadingStatusRequest, x_actor_label: str = Header(default="Desktop UI")
):
    try:
        return library_service.update_reading_status(project_id, publication_id, req, actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Organization (Collections & Tags) ---

@router.put("/projects/{project_id}/organization")
def set_organization(project_id: str, req: SetOrganizationRequest, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return library_service.set_organization(project_id, req, actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.get("/projects/{project_id}/organization")
def get_organization(project_id: str):
    try:
        return library_service.get_organization(project_id)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Manual Merge ---

@router.post("/projects/{project_id}/merges")
def merge_publications(project_id: str, req: MergePublicationsRequest, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return library_service.merge_publications(project_id, req, actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Annotations ---

@router.post("/projects/{project_id}/annotations", status_code=201)
def create_annotation(project_id: str, req: AnnotationCreate, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return annotation_service.create_annotation(project_id, req, actor_type="HUMAN", actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.get("/projects/{project_id}/annotations")
def list_annotations(
    project_id: str,
    publication_id: Optional[str] = None,
    question_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        return annotation_service.list_annotations(
            project_id=project_id,
            publication_id=publication_id,
            question_id=question_id,
            kind=kind,
            limit=limit,
            offset=offset,
        )
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.patch("/projects/{project_id}/annotations/{annotation_id}")
def update_annotation(
    project_id: str, annotation_id: str, req: AnnotationUpdate, x_actor_label: str = Header(default="Desktop UI")
):
    try:
        return annotation_service.update_annotation(project_id, annotation_id, req, actor_type="HUMAN", actor_label=x_actor_label)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Searches & Acquisition Runs ---

@router.post("/projects/{project_id}/searches")
def start_search(project_id: str, req: StartSearchRequest, x_actor_label: str = Header(default="Desktop UI")):
    try:
        run_dict = acquisition_service.start_search(project_id, req, actor_label=x_actor_label, run_in_background=True)
        return {
            **run_dict,
            "status_url": f"/api/v2/research/projects/{project_id}/runs/{run_dict['run_id']}",
        }
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.get("/projects/{project_id}/runs/{run_id}")
def get_run(project_id: str, run_id: str):
    try:
        return acquisition_service.get_run(project_id, run_id)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.post("/projects/{project_id}/runs/{run_id}/cancel")
def cancel_run(project_id: str, run_id: str):
    try:
        return acquisition_service.cancel_run(project_id, run_id)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Events Audit ---

@router.get("/projects/{project_id}/events")
def list_events(project_id: str, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
    with repo.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM research_projects WHERE project_id = ?", (project_id,))
        if not cur.fetchone():
            return format_error_response("NOT_FOUND", f"Project '{project_id}' not found", status_code=404)

        cur.execute("SELECT COUNT(*) FROM research_events WHERE project_id = ?", (project_id,))
        total = cur.fetchone()[0]

        cur.execute(
            """
            SELECT * FROM research_events
            WHERE project_id = ?
            ORDER BY created_at ASC, event_id ASC
            LIMIT ? OFFSET ?
            """,
            (project_id, limit, offset),
        )
        import json
        items = []
        for r in cur.fetchall():
            items.append({
                "event_id": r["event_id"],
                "project_id": r["project_id"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "action": r["action"],
                "actor_type": r["actor_type"],
                "actor_label": r["actor_label"],
                "before_json": json.loads(r["before_json"]) if r["before_json"] else None,
                "after_json": json.loads(r["after_json"]) if r["after_json"] else None,
                "created_at": r["created_at"],
            })
        return {"items": items, "total": total, "limit": limit, "offset": offset}


# --- Import & Export ---

@router.post("/projects/{project_id}/imports/preview")
def preview_import(project_id: str, req: ImportPreviewRequest):
    try:
        return interchange_service.preview_import(req.file_content, req.file_format, req.csv_mapping)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.post("/projects/{project_id}/imports/commit")
def commit_import(project_id: str, req: ImportCommitRequest, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return interchange_service.commit_import(
            project_id=project_id,
            preview_id=req.preview_id,
            file_hash=req.file_hash,
            idempotency_key=req.idempotency_key,
            actor_label=x_actor_label,
        )
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.post("/projects/{project_id}/exports")
def export_project(project_id: str, req: ExportProjectRequest):
    try:
        return interchange_service.export_project(
            project_id=project_id,
            scope=req.scope,
            export_format=req.format,
            collection_id=req.collection_id,
        )
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


# --- Restores ---

@router.post("/restores/preview")
def preview_restore(req: RestorePreviewRequest):
    try:
        return interchange_service.preview_restore(req.project_json_content)
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)


@router.post("/restores/commit")
def commit_restore(req: RestoreCommitRequest, x_actor_label: str = Header(default="Desktop UI")):
    try:
        return interchange_service.commit_restore(
            preview_id=req.preview_id,
            file_hash=req.file_hash,
            idempotency_key=req.idempotency_key,
            actor_label=x_actor_label,
        )
    except ResearchError as e:
        return format_error_response(e.code, e.message, e.details, e.status_code)
