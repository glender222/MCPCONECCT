"""
Data Access Layer and Transactional Repository for Block 2 Research System.
Enforces foreign keys, revision locking, idempotency receipts, and append-only event logging.
"""
from typing import Dict, Any, List, Optional, Tuple, Callable
import sqlite3
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from core.migrations.runner import utc_now_iso


def resolve_actor_type(actor_label: str) -> str:
    lbl = (actor_label or "").lower()
    if any(k in lbl for k in ("mcp", "agent", "ai ", "claude", "codex", "antigravity")):
        return "AGENT"
    return "HUMAN"


class ResearchError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class NotFoundError(ResearchError):
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(
            code="NOT_FOUND",
            message=f"{entity_type} '{entity_id}' not found",
            details={"entity_type": entity_type, "entity_id": entity_id},
            status_code=404,
        )


class RevisionConflictError(ResearchError):
    def __init__(self, current_revision: int, expected_revision: int):
        super().__init__(
            code="REVISION_CONFLICT",
            message=f"Revision conflict: expected revision {expected_revision}, but current revision is {current_revision}",
            details={"current_revision": current_revision, "expected_revision": expected_revision},
            status_code=409,
        )


class IdempotencyConflictError(ResearchError):
    def __init__(self, idempotency_key: str):
        super().__init__(
            code="IDEMPOTENCY_CONFLICT",
            message=f"Idempotency key '{idempotency_key}' was previously used with a different request payload",
            details={"idempotency_key": idempotency_key},
            status_code=409,
        )


class ProjectArchivedError(ResearchError):
    def __init__(self, project_id: str):
        super().__init__(
            code="PROJECT_ARCHIVED",
            message=f"Project '{project_id}' is archived and read-only",
            details={"project_id": project_id},
            status_code=409,
        )


class QuestionInUseError(ResearchError):
    def __init__(self, question_id: str, count: int):
        super().__init__(
            code="QUESTION_IN_USE",
            message=f"Question '{question_id}' cannot be removed because it is linked to {count} evidence annotations",
            details={"question_id": question_id, "evidence_count": count},
            status_code=409,
        )


class ScopeValidationError(ResearchError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="SCOPE_VALIDATION_ERROR",
            message=message,
            details=details or {},
            status_code=422,
        )


class ResearchRepository:
    """Manages transactional database access with isolation and concurrency safety."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.BASE_DIR / "data" / "mcpconecct.db")

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @staticmethod
    def hash_payload(data: Any) -> str:
        s = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def check_idempotency(
        self,
        conn: sqlite3.Connection,
        project_scope: str,
        operation: str,
        idempotency_key: Optional[str],
        request_payload: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns cached response dict if already executed with identical hash.
        Raises IdempotencyConflictError if executed with different payload.
        Returns None if not yet executed.
        """
        if not idempotency_key:
            return None

        req_hash = self.hash_payload(request_payload)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT request_hash, response_json
            FROM mutation_receipts
            WHERE project_scope = ? AND operation = ? AND idempotency_key = ?
            """,
            (project_scope, operation, idempotency_key),
        )
        row = cur.fetchone()
        if not row:
            return None

        saved_hash, saved_resp = row["request_hash"], row["response_json"]
        if saved_hash != req_hash:
            raise IdempotencyConflictError(idempotency_key)

        return json.loads(saved_resp)

    def record_receipt(
        self,
        conn: sqlite3.Connection,
        project_scope: str,
        operation: str,
        idempotency_key: Optional[str],
        request_payload: Any,
        response_dict: Dict[str, Any],
    ) -> None:
        if not idempotency_key:
            return

        req_hash = self.hash_payload(request_payload)
        resp_json = json.dumps(response_dict, default=str)
        conn.execute(
            """
            INSERT OR REPLACE INTO mutation_receipts (project_scope, operation, idempotency_key, request_hash, response_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_scope, operation, idempotency_key, req_hash, resp_json),
        )

    def log_event(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_type: str = "HUMAN",
        actor_label: str = "",
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Appends an event to research_events."""
        event_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        before_json = json.dumps(before, default=str) if before is not None else None
        after_json = json.dumps(after, default=str) if after is not None else None

        conn.execute(
            """
            INSERT INTO research_events (
                event_id, project_id, entity_type, entity_id, action,
                actor_type, actor_label, before_json, after_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, project_id, entity_type, entity_id, action, actor_type, actor_label, before_json, after_json, created_at),
        )
        return event_id

    def check_project_active(self, conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        """Ensures project exists and is not archived. Raises 404 or 409."""
        cur = conn.cursor()
        cur.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,))
        p = cur.fetchone()
        if not p:
            raise NotFoundError("Project", project_id)
        if p["archived"]:
            raise ProjectArchivedError(project_id)
        return p
