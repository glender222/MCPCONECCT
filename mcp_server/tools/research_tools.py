"""
MCP Tools for Block 2 Research System.
Exposes all research capabilities to Codex, Claude, and AI Agents, delegating
directly to core research services.
"""
from typing import Dict, Any, List, Optional
import json

from core.research.repository import ResearchRepository, ResearchError
from core.research.models import (
    ResearchProjectCreate,
    ResearchProjectUpdate,
    SetOutlineRequest,
    QuestionItem,
    ObjectiveItem,
    UpdateReadingStatusRequest,
    ReadingStatus,
    SetOrganizationRequest,
    CollectionDefinition,
    TagDefinition,
    CollectionAssignment,
    TagAssignment,
    AnnotationCreate,
    AnnotationUpdate,
    AnnotationKind,
    SourceKind,
    StartSearchRequest,
    ExportScope,
    ExportFormat,
    MergePublicationsRequest,
)
from core.research.projects import ProjectService
from core.research.library import LibraryService
from core.research.annotations import AnnotationService
from core.research.acquisitions import AcquisitionService
from core.research.interchange import InterchangeService

repo = ResearchRepository()
project_service = ProjectService(repo)
library_service = LibraryService(repo)
annotation_service = AnnotationService(repo)
acquisition_service = AcquisitionService(repo)
interchange_service = InterchangeService(repo)


def research_create_project(
    name: str,
    description: str = "",
    research_type: str = "",
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Creates a new research project workspace."""
    req = ResearchProjectCreate(
        name=name,
        description=description,
        research_type=research_type,
        idempotency_key=idempotency_key,
    )
    return project_service.create_project(req, actor_label=agent_name)


def research_list_projects(
    limit: int = 25, offset: int = 0, include_archived: bool = True
) -> Dict[str, Any]:
    """Lists research projects with pagination."""
    return project_service.list_projects(limit=limit, offset=offset, include_archived=include_archived)


def research_get_project(project_id: str) -> Dict[str, Any]:
    """Retrieves metadata of a research project."""
    return project_service.get_project(project_id)


def research_update_project(
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    research_type: Optional[str] = None,
    archived: Optional[bool] = None,
    expected_revision: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Updates metadata or archives a research project."""
    req = ResearchProjectUpdate(
        name=name,
        description=description,
        research_type=research_type,
        archived=archived,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return project_service.update_project(project_id, req, actor_label=agent_name)


def research_set_outline(
    project_id: str,
    expected_revision: int,
    questions: Optional[List[Dict[str, Any]]] = None,
    objectives: Optional[List[Dict[str, Any]]] = None,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Sets research questions and objectives atomically."""
    q_items = [QuestionItem(**q) for q in (questions or [])]
    o_items = [ObjectiveItem(**o) for o in (objectives or [])]
    req = SetOutlineRequest(
        expected_revision=expected_revision,
        questions=q_items,
        objectives=o_items,
        idempotency_key=idempotency_key,
    )
    return project_service.set_outline(project_id, req, actor_label=agent_name)


def research_list_publications(
    project_id: str,
    q: Optional[str] = None,
    reading_status: Optional[str] = None,
    collection_id: Optional[str] = None,
    tag_id: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> Dict[str, Any]:
    """Queries publications in a project's library with filtering."""
    return library_service.list_publications(
        project_id=project_id,
        q=q,
        reading_status=reading_status,
        collection_id=collection_id,
        tag_id=tag_id,
        limit=limit,
        offset=offset,
    )


def research_update_reading_status(
    project_id: str,
    publication_id: str,
    reading_status: str,
    expected_revision: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Updates reading status (UNREAD, READING, READ) for a publication in a project."""
    req = UpdateReadingStatusRequest(
        reading_status=ReadingStatus(reading_status),
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return library_service.update_reading_status(project_id, publication_id, req, actor_label=agent_name)


def research_set_organization(
    project_id: str,
    expected_revision: int,
    collections: Optional[List[Dict[str, Any]]] = None,
    tags: Optional[List[Dict[str, Any]]] = None,
    collection_members: Optional[List[Dict[str, Any]]] = None,
    publication_tags: Optional[List[Dict[str, Any]]] = None,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Defines collections, tags, and member assignments in a project."""
    c_defs = [CollectionDefinition(**c) for c in (collections or [])]
    t_defs = [TagDefinition(**t) for t in (tags or [])]
    cm_defs = [CollectionAssignment(**cm) for cm in (collection_members or [])]
    pt_defs = [TagAssignment(**pt) for pt in (publication_tags or [])]

    req = SetOrganizationRequest(
        expected_revision=expected_revision,
        collections=c_defs,
        tags=t_defs,
        collection_members=cm_defs,
        publication_tags=pt_defs,
        idempotency_key=idempotency_key,
    )
    return library_service.set_organization(project_id, req, actor_label=agent_name)


def research_create_annotation(
    project_id: str,
    publication_id: str,
    kind: str,
    body: str,
    source_kind: str,
    source_url: Optional[str] = None,
    locator: Optional[str] = None,
    question_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Creates a note, quote, or paraphrase annotation with strict provenance verification."""
    req = AnnotationCreate(
        publication_id=publication_id,
        kind=AnnotationKind(kind),
        body=body,
        source_kind=SourceKind(source_kind),
        source_url=source_url,
        locator=locator,
        question_id=question_id,
        actor_label=agent_name,
        idempotency_key=idempotency_key,
    )
    return annotation_service.create_annotation(project_id, req, actor_type="AGENT", actor_label=agent_name)


def research_list_annotations(
    project_id: str,
    publication_id: Optional[str] = None,
    question_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> Dict[str, Any]:
    """Lists annotations within a project."""
    return annotation_service.list_annotations(
        project_id=project_id,
        publication_id=publication_id,
        question_id=question_id,
        kind=kind,
        limit=limit,
        offset=offset,
    )


def research_update_annotation(
    project_id: str,
    annotation_id: str,
    expected_revision: int,
    body: Optional[str] = None,
    source_url: Optional[str] = None,
    locator: Optional[str] = None,
    question_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Updates an existing annotation."""
    req = AnnotationUpdate(
        body=body,
        source_url=source_url,
        locator=locator,
        question_id=question_id,
        expected_revision=expected_revision,
        actor_label=agent_name,
        idempotency_key=idempotency_key,
    )
    return annotation_service.update_annotation(project_id, annotation_id, req, actor_type="AGENT", actor_label=agent_name)


def research_start_search(
    project_id: str,
    database: str,
    query: str,
    search_mode: str = "advanced",
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    doc_types: Optional[List[str]] = None,
    max_records: int = 50,
    enrich_doi: bool = True,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Initiates an asynchronous academic search run ingesting into project library."""
    req = StartSearchRequest(
        database=database,
        query=query,
        search_mode=search_mode,
        year_start=year_start,
        year_end=year_end,
        doc_types=doc_types,
        max_records=max_records,
        enrich_doi=enrich_doi,
        idempotency_key=idempotency_key,
    )
    run_dict = acquisition_service.start_search(project_id, req, actor_label=agent_name, run_in_background=True)
    return {
        **run_dict,
        "status_url": f"/api/v2/research/projects/{project_id}/runs/{run_dict['run_id']}",
    }


def research_get_run(project_id: str, run_id: str) -> Dict[str, Any]:
    """Gets the status and counts of an acquisition run."""
    return acquisition_service.get_run(project_id, run_id)


def research_cancel_run(project_id: str, run_id: str) -> Dict[str, Any]:
    """Cancels an ongoing acquisition run."""
    return acquisition_service.cancel_run(project_id, run_id)


def research_list_events(project_id: str, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
    """Lists audit events for a project."""
    with repo.get_connection() as conn:
        cur = conn.cursor()
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


def research_preview_import(
    file_content: str,
    file_format: str,
    csv_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Previews an import file (BibTeX, RIS, CSV) without modifying database."""
    res = interchange_service.preview_import(file_content, file_format, csv_mapping)
    return res.model_dump()


def research_commit_import(
    project_id: str,
    preview_id: str,
    file_hash: str,
    idempotency_key: str,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Commits previewed import records into project library."""
    res = interchange_service.commit_import(
        project_id=project_id,
        preview_id=preview_id,
        file_hash=file_hash,
        idempotency_key=idempotency_key,
        actor_label=agent_name,
    )
    return res.model_dump()


def research_export_project(
    project_id: str,
    scope: str = "ALL",
    export_format: str = "BIB",
    collection_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Exports bibliography or sanitized PROJECT_JSON."""
    return interchange_service.export_project(
        project_id=project_id,
        scope=ExportScope(scope),
        export_format=ExportFormat(export_format),
        collection_id=collection_id,
    )


def research_preview_restore(project_json_content: str) -> Dict[str, Any]:
    """Previews a project JSON restoration."""
    res = interchange_service.preview_restore(project_json_content)
    return res.model_dump()


def research_commit_restore(
    preview_id: str,
    file_hash: str,
    idempotency_key: str,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Commits a project restoration into a new project."""
    res = interchange_service.commit_restore(
        preview_id=preview_id,
        file_hash=file_hash,
        idempotency_key=idempotency_key,
        actor_label=agent_name,
    )
    return res.model_dump()


def research_merge_publications(
    project_id: str,
    survivor_id: str,
    absorbed_id: str,
    idempotency_key: Optional[str] = None,
    agent_name: str = "AI Agent (MCP)",
) -> Dict[str, Any]:
    """Manually merges two publications within project."""
    req = MergePublicationsRequest(
        survivor_id=survivor_id,
        absorbed_id=absorbed_id,
        idempotency_key=idempotency_key,
    )
    return library_service.merge_publications(project_id, req, actor_label=agent_name)


def register_research_tools(mcp) -> None:
    """Registers all Block 2 research tools on the MCP server instance."""
    mcp.tool()(research_create_project)
    mcp.tool()(research_list_projects)
    mcp.tool()(research_get_project)
    mcp.tool()(research_update_project)
    mcp.tool()(research_set_outline)
    mcp.tool()(research_list_publications)
    mcp.tool()(research_update_reading_status)
    mcp.tool()(research_set_organization)
    mcp.tool()(research_create_annotation)
    mcp.tool()(research_list_annotations)
    mcp.tool()(research_update_annotation)
    mcp.tool()(research_start_search)
    mcp.tool()(research_get_run)
    mcp.tool()(research_cancel_run)
    mcp.tool()(research_list_events)
    mcp.tool()(research_preview_import)
    mcp.tool()(research_commit_import)
    mcp.tool()(research_export_project)
    mcp.tool()(research_preview_restore)
    mcp.tool()(research_commit_restore)
    mcp.tool()(research_merge_publications)
