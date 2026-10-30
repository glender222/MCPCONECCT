"""
Project Lifecycle, Research Questions & Objectives Service.
Implements Section 4 & 8: Projects, outline, revisions, idempotency, event logging.
"""
from typing import Dict, Any, List, Optional
import uuid
import json
import sqlite3

from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    RevisionConflictError,
    ProjectArchivedError,
    QuestionInUseError,
    ScopeValidationError,
    resolve_actor_type,
)
from core.research.models import (
    ResearchProjectCreate,
    ResearchProjectUpdate,
    SetOutlineRequest,
)
from core.migrations.runner import utc_now_iso


class ProjectService:
    def __init__(self, repo: Optional[ResearchRepository] = None):
        self.repo = repo or ResearchRepository()

    def create_project(self, req: ResearchProjectCreate, actor_label: str = "") -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, "GLOBAL", "CREATE_PROJECT", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            project_id = str(uuid.uuid4())
            now = utc_now_iso()

            conn.execute(
                """
                INSERT INTO research_projects (
                    project_id, name, description, research_type, archived, created_at, updated_at, revision
                ) VALUES (?, ?, ?, ?, 0, ?, ?, 1)
                """,
                (project_id, req.name, req.description, req.research_type, now, now),
            )

            result = {
                "project_id": project_id,
                "name": req.name,
                "description": req.description,
                "research_type": req.research_type,
                "archived": False,
                "created_at": now,
                "updated_at": now,
                "revision": 1,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="PROJECT",
                entity_id=project_id,
                action="CREATED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before=None,
                after=result,
            )

            self.repo.record_receipt(
                conn, "GLOBAL", "CREATE_PROJECT", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()
            return result

    def get_project(self, project_id: str) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,))
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Project", project_id)
            return {
                "project_id": row["project_id"],
                "name": row["name"],
                "description": row["description"],
                "research_type": row["research_type"],
                "archived": bool(row["archived"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "revision": row["revision"],
            }

    def list_projects(
        self, limit: int = 25, offset: int = 0, include_archived: bool = True
    ) -> Dict[str, Any]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            where_sql = "" if include_archived else "WHERE archived = 0"
            cur.execute(f"SELECT COUNT(*) FROM research_projects {where_sql}")
            total = cur.fetchone()[0]

            cur.execute(
                f"""
                SELECT * FROM research_projects
                {where_sql}
                ORDER BY created_at ASC, project_id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = cur.fetchall()

            items = [
                {
                    "project_id": r["project_id"],
                    "name": r["name"],
                    "description": r["description"],
                    "research_type": r["research_type"],
                    "archived": bool(r["archived"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "revision": r["revision"],
                }
                for r in rows
            ]

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def update_project(
        self, project_id: str, req: ResearchProjectUpdate, actor_label: str = ""
    ) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "UPDATE_PROJECT", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            cur = conn.cursor()
            cur.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,))
            row = cur.fetchone()
            if not row:
                raise NotFoundError("Project", project_id)

            current_rev = row["revision"]
            if req.expected_revision is not None and current_rev != req.expected_revision:
                raise RevisionConflictError(current_rev, req.expected_revision)

            # If project is currently archived, only allow un-archiving (archived=False)
            if row["archived"] and req.archived is not False:
                raise ProjectArchivedError(project_id)

            new_name = req.name if req.name is not None else row["name"]
            new_desc = req.description if req.description is not None else row["description"]
            new_type = req.research_type if req.research_type is not None else row["research_type"]
            new_archived = int(req.archived) if req.archived is not None else row["archived"]

            new_rev = current_rev + 1
            now = utc_now_iso()

            conn.execute(
                """
                UPDATE research_projects
                SET name = ?, description = ?, research_type = ?, archived = ?, updated_at = ?, revision = ?
                WHERE project_id = ?
                """,
                (new_name, new_desc, new_type, new_archived, now, new_rev, project_id),
            )

            before = {
                "name": row["name"],
                "description": row["description"],
                "research_type": row["research_type"],
                "archived": bool(row["archived"]),
                "revision": current_rev,
            }
            after = {
                "project_id": project_id,
                "name": new_name,
                "description": new_desc,
                "research_type": new_type,
                "archived": bool(new_archived),
                "created_at": row["created_at"],
                "updated_at": now,
                "revision": new_rev,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="PROJECT",
                entity_id=project_id,
                action="UPDATED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before=before,
                after=after,
            )

            self.repo.record_receipt(
                conn, project_id, "UPDATE_PROJECT", req.idempotency_key, req.model_dump(), after
            )
            conn.commit()
            return after

    def set_outline(
        self, project_id: str, req: SetOutlineRequest, actor_label: str = ""
    ) -> Dict[str, Any]:
        """
        Replaces questions and objectives atomically in a transaction using expected_revision.
        Validates that no question with linked evidence is removed (409 QUESTION_IN_USE).
        """
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "SET_OUTLINE", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            p = self.repo.check_project_active(conn, project_id)
            current_rev = p["revision"]
            if current_rev != req.expected_revision:
                raise RevisionConflictError(current_rev, req.expected_revision)

            cur = conn.cursor()

            # Existing questions in this project
            cur.execute("SELECT question_id, revision FROM research_questions WHERE project_id = ?", (project_id,))
            existing_questions = {r["question_id"]: r["revision"] for r in cur.fetchall()}

            # New incoming question IDs
            incoming_q_ids = {q.question_id for q in req.questions if q.question_id}

            # Check if any to-be-removed question has linked annotations
            for old_qid in existing_questions:
                if old_qid not in incoming_q_ids:
                    cur.execute(
                        "SELECT COUNT(*) FROM annotations WHERE project_id = ? AND question_id = ?",
                        (project_id, old_qid),
                    )
                    annot_count = cur.fetchone()[0]
                    if annot_count > 0:
                        raise QuestionInUseError(old_qid, annot_count)

            # Delete old questions and objectives
            conn.execute("DELETE FROM research_questions WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM research_objectives WHERE project_id = ?", (project_id,))

            # Insert questions
            saved_questions = []
            for q in req.questions:
                qid = q.question_id or str(uuid.uuid4())
                q_rev = (existing_questions.get(qid, 0) + 1) if qid in existing_questions else 1
                conn.execute(
                    """
                    INSERT INTO research_questions (question_id, project_id, text, position, revision)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (qid, project_id, q.text, q.position, q_rev),
                )
                saved_questions.append({
                    "question_id": qid,
                    "text": q.text,
                    "position": q.position,
                    "revision": q_rev,
                })

            # Insert objectives
            cur.execute("SELECT objective_id, revision FROM research_objectives WHERE project_id = ?", (project_id,))
            existing_objs = {r["objective_id"]: r["revision"] for r in cur.fetchall()}

            saved_objectives = []
            for o in req.objectives:
                oid = o.objective_id or str(uuid.uuid4())
                o_rev = (existing_objs.get(oid, 0) + 1) if oid in existing_objs else 1
                conn.execute(
                    """
                    INSERT INTO research_objectives (objective_id, project_id, text, position, revision)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (oid, project_id, o.text, o.position, o_rev),
                )
                saved_objectives.append({
                    "objective_id": oid,
                    "text": o.text,
                    "position": o.position,
                    "revision": o_rev,
                })

            # Increment project revision
            new_rev = current_rev + 1
            now = utc_now_iso()
            conn.execute(
                "UPDATE research_projects SET updated_at = ?, revision = ? WHERE project_id = ?",
                (now, new_rev, project_id),
            )

            result = {
                "project_id": project_id,
                "revision": new_rev,
                "questions": saved_questions,
                "objectives": saved_objectives,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="PROJECT",
                entity_id=project_id,
                action="OUTLINE_UPDATED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before={"revision": current_rev},
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "SET_OUTLINE", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()
            return result

    def get_outline(self, project_id: str) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT revision FROM research_projects WHERE project_id = ?", (project_id,))
            p = cur.fetchone()
            if not p:
                raise NotFoundError("Project", project_id)

            cur.execute(
                "SELECT * FROM research_questions WHERE project_id = ? ORDER BY position ASC, question_id ASC",
                (project_id,),
            )
            questions = [
                {
                    "question_id": r["question_id"],
                    "text": r["text"],
                    "position": r["position"],
                    "revision": r["revision"],
                }
                for r in cur.fetchall()
            ]

            cur.execute(
                "SELECT * FROM research_objectives WHERE project_id = ? ORDER BY position ASC, objective_id ASC",
                (project_id,),
            )
            objectives = [
                {
                    "objective_id": r["objective_id"],
                    "text": r["text"],
                    "position": r["position"],
                    "revision": r["revision"],
                }
                for r in cur.fetchall()
            ]

            return {
                "project_id": project_id,
                "revision": p["revision"],
                "questions": questions,
                "objectives": objectives,
            }
