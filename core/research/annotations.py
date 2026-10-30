"""
Annotations, Notes & Textual Evidence Service.
Implements Section 6 & Acceptance Test A08, A09:
Strict validation of NOTE, QUOTE, PARAPHRASE, source_kind (NONE, ABSTRACT, FULLTEXT),
locator rules, question project scope, and append-only revisioned event logging.
"""
from typing import Dict, Any, List, Optional
import uuid
import json
import sqlite3

from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    RevisionConflictError,
    ScopeValidationError,
)
from core.research.models import (
    AnnotationKind,
    SourceKind,
    ActorType,
    AnnotationCreate,
    AnnotationUpdate,
)
from core.migrations.runner import utc_now_iso


def get_provenance_badge(kind: str, source_kind: str, locator: Optional[str]) -> str:
    if source_kind == "ABSTRACT":
        return "Basado en resumen"
    elif source_kind == "FULLTEXT":
        loc_str = f": {locator}" if locator else ""
        return f"Texto completo{loc_str}"
    return "Nota libre"


class AnnotationService:
    def __init__(self, repo: Optional[ResearchRepository] = None):
        self.repo = repo or ResearchRepository()

    def create_annotation(
        self,
        project_id: str,
        req: AnnotationCreate,
        actor_type: str = "HUMAN",
        actor_label: str = "",
    ) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "CREATE_ANNOTATION", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            self.repo.check_project_active(conn, project_id)

            cur = conn.cursor()

            # Check publication exists in this project
            cur.execute(
                "SELECT 1 FROM project_publications WHERE project_id = ? AND publication_id = ?",
                (project_id, req.publication_id),
            )
            if not cur.fetchone():
                # Check alias
                cur.execute("SELECT publication_id FROM publication_aliases WHERE old_id = ?", (req.publication_id,))
                alias = cur.fetchone()
                if alias:
                    req.publication_id = alias[0]
                    cur.execute(
                        "SELECT 1 FROM project_publications WHERE project_id = ? AND publication_id = ?",
                        (project_id, req.publication_id),
                    )
                if not cur.fetchone():
                    raise ScopeValidationError(
                        f"Publication '{req.publication_id}' does not belong to project '{project_id}'"
                    )

            # Check question scope if provided
            if req.question_id:
                cur.execute(
                    "SELECT 1 FROM research_questions WHERE question_id = ? AND project_id = ?",
                    (req.question_id, project_id),
                )
                if not cur.fetchone():
                    raise ScopeValidationError(
                        f"Question '{req.question_id}' does not belong to project '{project_id}'"
                    )

            annotation_id = str(uuid.uuid4())
            now = utc_now_iso()
            badge = get_provenance_badge(req.kind.value, req.source_kind.value, req.locator)

            conn.execute(
                """
                INSERT INTO annotations (
                    annotation_id, project_id, publication_id, kind, body, source_kind,
                    source_url, locator, question_id, actor_type, actor_label,
                    created_at, updated_at, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    annotation_id,
                    project_id,
                    req.publication_id,
                    req.kind.value,
                    req.body,
                    req.source_kind.value,
                    req.source_url,
                    req.locator,
                    req.question_id,
                    actor_type,
                    actor_label or req.actor_label,
                    now,
                    now,
                ),
            )

            result = {
                "annotation_id": annotation_id,
                "project_id": project_id,
                "publication_id": req.publication_id,
                "kind": req.kind.value,
                "body": req.body,
                "source_kind": req.source_kind.value,
                "source_url": req.source_url,
                "locator": req.locator,
                "question_id": req.question_id,
                "actor_type": actor_type,
                "actor_label": actor_label or req.actor_label,
                "created_at": now,
                "updated_at": now,
                "revision": 1,
                "provenance_badge": badge,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="ANNOTATION",
                entity_id=annotation_id,
                action="CREATED",
                actor_type=actor_type,
                actor_label=actor_label or req.actor_label,
                before=None,
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "CREATE_ANNOTATION", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()
            return result

    def update_annotation(
        self,
        project_id: str,
        annotation_id: str,
        req: AnnotationUpdate,
        actor_type: str = "HUMAN",
        actor_label: str = "",
    ) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "UPDATE_ANNOTATION", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            self.repo.check_project_active(conn, project_id)

            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM annotations WHERE annotation_id = ? AND project_id = ?",
                (annotation_id, project_id),
            )
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Annotation in project", annotation_id)

            current_rev = row["revision"]
            if req.expected_revision != current_rev:
                raise RevisionConflictError(current_rev, req.expected_revision)

            # Check question scope if provided
            if req.question_id is not None:
                cur.execute(
                    "SELECT 1 FROM research_questions WHERE question_id = ? AND project_id = ?",
                    (req.question_id, project_id),
                )
                if not cur.fetchone():
                    raise ScopeValidationError(
                        f"Question '{req.question_id}' does not belong to project '{project_id}'"
                    )

            new_body = req.body if req.body is not None else row["body"]
            new_url = req.source_url if req.source_url is not None else row["source_url"]
            new_locator = req.locator if req.locator is not None else row["locator"]
            new_qid = req.question_id if req.question_id is not None else row["question_id"]
            new_rev = current_rev + 1
            now = utc_now_iso()

            conn.execute(
                """
                UPDATE annotations
                SET body = ?, source_url = ?, locator = ?, question_id = ?, updated_at = ?, revision = ?
                WHERE annotation_id = ? AND project_id = ?
                """,
                (new_body, new_url, new_locator, new_qid, now, new_rev, annotation_id, project_id),
            )

            badge = get_provenance_badge(row["kind"], row["source_kind"], new_locator)
            before = dict(row)
            after = {
                "annotation_id": annotation_id,
                "project_id": project_id,
                "publication_id": row["publication_id"],
                "kind": row["kind"],
                "body": new_body,
                "source_kind": row["source_kind"],
                "source_url": new_url,
                "locator": new_locator,
                "question_id": new_qid,
                "actor_type": actor_type,
                "actor_label": actor_label or req.actor_label,
                "created_at": row["created_at"],
                "updated_at": now,
                "revision": new_rev,
                "provenance_badge": badge,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="ANNOTATION",
                entity_id=annotation_id,
                action="UPDATED",
                actor_type=actor_type,
                actor_label=actor_label or req.actor_label,
                before=before,
                after=after,
            )

            self.repo.record_receipt(
                conn, project_id, "UPDATE_ANNOTATION", req.idempotency_key, req.model_dump(), after
            )
            conn.commit()
            return after

    def list_annotations(
        self,
        project_id: str,
        publication_id: Optional[str] = None,
        question_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM research_projects WHERE project_id = ?", (project_id,))
            if not cur.fetchone():
                raise NotFoundError("Project", project_id)

            where_clauses = ["project_id = ?"]
            params: List[Any] = [project_id]

            if publication_id:
                # Handle alias
                cur.execute("SELECT publication_id FROM publication_aliases WHERE old_id = ?", (publication_id,))
                alias = cur.fetchone()
                target_pub_id = alias[0] if alias else publication_id
                where_clauses.append("publication_id = ?")
                params.append(target_pub_id)

            if question_id:
                where_clauses.append("question_id = ?")
                params.append(question_id)

            if kind:
                where_clauses.append("kind = ?")
                params.append(kind.upper())

            where_sql = " AND ".join(where_clauses)

            cur.execute(f"SELECT COUNT(*) FROM annotations WHERE {where_sql}", params)
            total = cur.fetchone()[0]

            cur.execute(
                f"""
                SELECT * FROM annotations
                WHERE {where_sql}
                ORDER BY created_at ASC, annotation_id ASC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

            items = [
                {
                    "annotation_id": r["annotation_id"],
                    "project_id": r["project_id"],
                    "publication_id": r["publication_id"],
                    "kind": r["kind"],
                    "body": r["body"],
                    "source_kind": r["source_kind"],
                    "source_url": r["source_url"],
                    "locator": r["locator"],
                    "question_id": r["question_id"],
                    "actor_type": r["actor_type"],
                    "actor_label": r["actor_label"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "revision": r["revision"],
                    "provenance_badge": get_provenance_badge(r["kind"], r["source_kind"], r["locator"]),
                }
                for r in rows
            ]

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def get_annotation(self, project_id: str, annotation_id: str) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM annotations WHERE project_id = ? AND annotation_id = ?",
                (project_id, annotation_id),
            )
            r = cur.fetchone()
            if not r:
                raise NotFoundError("Annotation in project", annotation_id)
            return {
                "annotation_id": r["annotation_id"],
                "project_id": r["project_id"],
                "publication_id": r["publication_id"],
                "kind": r["kind"],
                "body": r["body"],
                "source_kind": r["source_kind"],
                "source_url": r["source_url"],
                "locator": r["locator"],
                "question_id": r["question_id"],
                "actor_type": r["actor_type"],
                "actor_label": r["actor_label"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "revision": r["revision"],
                "provenance_badge": get_provenance_badge(r["kind"], r["source_kind"], r["locator"]),
            }
