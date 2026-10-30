"""
Acquisition Runs, Search Execution & Source Observations Service.
Implements Section 5 (Identity & Dedup rules) & Section 7 (Run lifecycle, partial runs, cancellation).
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import uuid
import json
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone

from config import settings
from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    ProjectArchivedError,
    resolve_actor_type,
)
from core.research.models import (
    RunKind,
    RunStatus,
    StartSearchRequest,
    RunResponse,
)
from core.migrations.runner import utc_now_iso
from platforms.base import normalize_doi, normalize_title


def normalize_author_name(author: str) -> str:
    """NFKC, casefold and normalized internal spaces."""
    if not author:
        return ""
    norm = unicodedata.normalize("NFKC", author).strip().casefold()
    return " ".join(norm.split())


def authors_match_normalized(list_a: List[str], list_b: List[str]) -> bool:
    """Strict comparison of author lists with NFKC, casefold, preserving order."""
    if not list_a or not list_b:
        return False
    if len(list_a) != len(list_b):
        return False
    for a, b in zip(list_a, list_b):
        if normalize_author_name(a) != normalize_author_name(b):
            return False
    return True


class AcquisitionService:
    def __init__(self, repo: Optional[ResearchRepository] = None):
        self.repo = repo or ResearchRepository()
        self._cancel_tokens: Dict[str, bool] = {}
        self._lock = threading.Lock()

    def request_cancellation(self, run_id: str) -> bool:
        with self._lock:
            self._cancel_tokens[run_id] = True
        return True

    def is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            return self._cancel_tokens.get(run_id, False)

    def get_run(self, project_id: str, run_id: str) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM acquisition_runs WHERE project_id = ? AND run_id = ?",
                (project_id, run_id),
            )
            r = cur.fetchone()
            if not r:
                raise NotFoundError("AcquisitionRun", run_id)
            return {
                "run_id": r["run_id"],
                "project_id": r["project_id"],
                "kind": r["kind"],
                "status": r["status"],
                "request_json": json.loads(r["request_json"]) if r["request_json"] else {},
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
                "reported_total": r["reported_total"],
                "observed_count": r["observed_count"],
                "unique_count": r["unique_count"],
                "stop_reason": r["stop_reason"],
            }

    def cancel_run(self, project_id: str, run_id: str) -> Dict[str, Any]:
        self.request_cancellation(run_id)
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM acquisition_runs WHERE project_id = ? AND run_id = ?",
                (project_id, run_id),
            )
            r = cur.fetchone()
            if not r:
                raise NotFoundError("AcquisitionRun", run_id)

            if r["status"] in ("QUEUED", "RUNNING"):
                conn.execute(
                    """
                    UPDATE acquisition_runs
                    SET status = 'CANCELLED', stop_reason = 'USER_CANCELLED', finished_at = ?
                    WHERE project_id = ? AND run_id = ?
                    """,
                    (utc_now_iso(), project_id, run_id),
                )
                conn.commit()

        return self.get_run(project_id, run_id)

    def start_search(
        self,
        project_id: str,
        req: StartSearchRequest,
        actor_label: str = "",
        run_in_background: bool = True,
    ) -> Dict[str, Any]:
        """
        Creates an acquisition run for a search and starts ingestion.
        """
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "START_SEARCH", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            self.repo.check_project_active(conn, project_id)

            run_id = str(uuid.uuid4())
            now = utc_now_iso()
            req_dict = req.model_dump()
            req_dict["app_version"] = "2.0.0"

            conn.execute(
                """
                INSERT INTO acquisition_runs (
                    run_id, project_id, kind, status, request_json, started_at,
                    observed_count, unique_count
                ) VALUES (?, ?, 'SEARCH', 'QUEUED', ?, ?, 0, 0)
                """,
                (run_id, project_id, json.dumps(req_dict), now),
            )

            result = {
                "run_id": run_id,
                "project_id": project_id,
                "kind": "SEARCH",
                "status": "QUEUED",
                "request_json": req_dict,
                "started_at": now,
                "finished_at": None,
                "reported_total": None,
                "observed_count": 0,
                "unique_count": 0,
                "stop_reason": None,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="ACQUISITION_RUN",
                entity_id=run_id,
                action="SEARCH_STARTED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before=None,
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "START_SEARCH", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()

        if run_in_background:
            t = threading.Thread(
                target=self._execute_search_run,
                args=(project_id, run_id, req),
                daemon=True,
            )
            t.start()
        else:
            self._execute_search_run(project_id, run_id, req)

        return self.get_run(project_id, run_id)

    def _execute_search_run(self, project_id: str, run_id: str, req: StartSearchRequest) -> None:
        """Internal execution loop of the acquisition run with pagination, error & limit handling."""
        with self.repo.get_connection() as conn:
            conn.execute(
                "UPDATE acquisition_runs SET status = 'RUNNING' WHERE run_id = ?",
                (run_id,),
            )
            conn.commit()

        from platforms import get_platform
        platform = get_platform(req.database)

        page = 1
        page_size = 25
        total_observed = 0
        reported_total = None
        stop_reason = None
        final_status = "COMPLETED"

        try:
            while total_observed < req.max_records:
                if self.is_cancelled(run_id):
                    final_status = "CANCELLED"
                    stop_reason = "USER_CANCELLED"
                    break

                try:
                    res = platform.search(
                        query=req.query,
                        year_start=req.year_start,
                        year_end=req.year_end,
                        doc_types=req.doc_types,
                        page=page,
                        page_size=page_size,
                    )
                except Exception as net_err:
                    err_str = str(net_err)
                    is_waf = any(w in err_str.lower() for w in ["waf", "cloudflare", "403 forbidden", "captcha"])
                    if is_waf:
                        stop_reason = "WAF"
                    else:
                        stop_reason = "ERROR"

                    if total_observed > 0:
                        final_status = "PARTIAL"
                    else:
                        final_status = "FAILED"
                    break

                if reported_total is None:
                    reported_total = res.get("total_results")

                raw_papers = res.get("papers", [])
                if not raw_papers:
                    # End of results from platform
                    break

                # Ingest page papers transactionally
                with self.repo.get_connection() as conn:
                    added_obs = self.ingest_batch_of_papers(
                        conn, project_id, run_id, raw_papers, enrich=req.enrich_doi
                    )
                    conn.commit()

                total_observed += added_obs
                page += 1

                # If platform returned fewer than page_size, end reached
                if len(raw_papers) < page_size:
                    break

            if final_status == "COMPLETED" and reported_total is not None and total_observed >= req.max_records and total_observed < reported_total:
                final_status = "PARTIAL"
                stop_reason = "LIMIT"

        except Exception as unhandled:
            stop_reason = f"UNHANDLED: {unhandled}"
            final_status = "PARTIAL" if total_observed > 0 else "FAILED"

        # Finalize run in DB
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(DISTINCT publication_id) FROM source_observations WHERE run_id = ?", (run_id,))
            unique_count = cur.fetchone()[0]

            now = utc_now_iso()
            conn.execute(
                """
                UPDATE acquisition_runs
                SET status = ?, finished_at = ?, reported_total = ?, observed_count = ?,
                    unique_count = ?, stop_reason = ?
                WHERE run_id = ?
                """,
                (final_status, now, reported_total, total_observed, unique_count, stop_reason, run_id),
            )
            conn.commit()

    def ingest_batch_of_papers(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        run_id: str,
        raw_papers: List[Any],
        enrich: bool = False,
    ) -> int:
        """
        Applies Section 5 identity and dedup rules to ingest raw items into
        publications, project_publications, and source_observations.
        Returns count of newly observed records.
        """
        cur = conn.cursor()
        now = utc_now_iso()
        observed_in_batch = 0

        for item in raw_papers:
            # Handle dict or CanonicalPaper
            if hasattr(item, "model_dump"):
                d = item.model_dump()
            elif isinstance(item, dict):
                d = item
            else:
                continue

            doi = normalize_doi(d.get("doi"))
            raw_title = (d.get("title") or "").strip()
            norm_title = normalize_title(raw_title)
            authors = d.get("authors") or []
            year = d.get("year")
            venue = d.get("venue") or ""
            doc_type = d.get("doc_type") or "other"
            abstract = (d.get("abstract") or "").strip()
            keywords = d.get("keywords") or []
            url = d.get("url") or ""
            raw_bibtex_key = d.get("raw_bibtex_key") or ""

            # Source record key for observation idempotency within run
            if doi:
                rec_key = f"doi:{doi}"
            else:
                first_auth = normalize_author_name(authors[0]) if authors else "anon"
                rec_key = f"title:{norm_title}|year:{year}|author:{first_auth}"

            # Check rule 7: "Repetir una página del mismo run_id no añade observaciones."
            cur.execute(
                "SELECT 1 FROM source_observations WHERE run_id = ? AND source_record_key = ?",
                (run_id, rec_key),
            )
            if cur.fetchone():
                continue  # Observation already recorded in this run!

            # Identity & Dedup Resolution (Section 5)
            publication_id: Optional[str] = None

            # Rule 1: Same normalized DOI -> reuse publication_id
            if doi:
                cur.execute("SELECT publication_id, title, abstract FROM publications WHERE doi = ?", (doi,))
                found = cur.fetchone()
                if found:
                    publication_id = found["publication_id"]
                    # If abstract in existing is shorter, enrich with longer (Rule 5)
                    if enrich and abstract and len(abstract) > len(found["abstract"] or ""):
                        conn.execute(
                            "UPDATE publications SET abstract = ?, updated_at = ? WHERE publication_id = ?",
                            (abstract, now, publication_id),
                        )
                else:
                    # Check aliases
                    cur.execute("SELECT publication_id FROM publication_aliases WHERE old_id = ?", (rec_key,))
                    alias_row = cur.fetchone()
                    if alias_row:
                        publication_id = alias_row["publication_id"]

            # Rule 3: Without DOI -> reuse ONLY if normalized title, known year, and matching non-empty authors list match
            if not publication_id and not doi:
                if norm_title and year:
                    cur.execute(
                        "SELECT publication_id, authors_json, abstract FROM publications WHERE normalized_title = ? AND year = ? AND doi IS NULL",
                        (norm_title, year),
                    )
                    candidates = cur.fetchall()
                    for cand in candidates:
                        cand_authors = json.loads(cand["authors_json"]) if cand["authors_json"] else []
                        if authors_match_normalized(authors, cand_authors):
                            publication_id = cand["publication_id"]
                            # Rule 5: enrich abstract if longer
                            if enrich and abstract and len(abstract) > len(cand["abstract"] or ""):
                                conn.execute(
                                    "UPDATE publications SET abstract = ?, updated_at = ? WHERE publication_id = ?",
                                    (abstract, now, publication_id),
                                )
                            break

            # If still not found -> create new publication
            if not publication_id:
                publication_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO publications (
                        publication_id, doi, title, normalized_title, authors_json, year,
                        venue, doc_type, abstract, keywords_json, url, raw_bibtex_key,
                        created_at, updated_at, revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        publication_id,
                        doi,
                        raw_title,
                        norm_title,
                        json.dumps(authors),
                        year,
                        venue,
                        doc_type,
                        abstract,
                        json.dumps(keywords),
                        url,
                        raw_bibtex_key,
                        now,
                        now,
                    ),
                )

            # Ensure membership in project_publications
            # Rule 7: New memberships created as UNREAD and NEVER reset existing status!
            conn.execute(
                """
                INSERT OR IGNORE INTO project_publications (project_id, publication_id, reading_status, added_at, revision)
                VALUES (?, ?, 'UNREAD', ?, 1)
                """,
                (project_id, publication_id, now),
            )

            # Insert source observation
            obs_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO source_observations (
                    observation_id, run_id, publication_id, source_record_key, raw_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (obs_id, run_id, publication_id, rec_key, json.dumps(d), now),
            )

            observed_in_batch += 1

        return observed_in_batch
