"""
Interchange Service: Import (BibTeX, RIS, CSV), Export (BIB, RIS, CSV, PROJECT_JSON),
and Atomic Project Restore.
Implements Section 9 & Acceptance Tests A14, A15, A16, A17.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import uuid
import json
import csv
import io
import hashlib
import time
import sqlite3
from datetime import datetime, timezone

from core.research.repository import (
    ResearchRepository,
    ResearchError,
    NotFoundError,
    ScopeValidationError,
    resolve_actor_type,
)
from core.research.models import (
    ExportScope,
    ExportFormat,
    RowErrorDetail,
    ImportPreviewResponse,
    ImportCommitResponse,
    RestorePreviewResponse,
    RestoreCommitResponse,
)
from core.research.acquisitions import AcquisitionService
from core.migrations.runner import utc_now_iso
from platforms.base import normalize_doi, normalize_title


class PreviewExpiredOrChangedError(ResearchError):
    def __init__(self, preview_id: str):
        super().__init__(
            code="PREVIEW_EXPIRED_OR_CHANGED",
            message=f"Preview '{preview_id}' has expired or the file content was modified",
            details={"preview_id": preview_id},
            status_code=409,
        )


class RestoreValidationError(ResearchError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="RESTORE_VALIDATION_ERROR",
            message=message,
            details=details or {},
            status_code=422,
        )


# --- Parsers ---

def parse_csv_records(
    content: str, column_mapping: Optional[Dict[str, str]] = None
) -> Tuple[List[Dict[str, Any]], List[RowErrorDetail]]:
    """
    RFC4180 CSV parser with BOM tolerance.
    column_mapping: canonical_field -> csv_header (e.g. {"title": "Title", "authors": "Authors"})
    """
    # Strip UTF-8 BOM if present
    if content.startswith("\ufeff"):
        content = content[1:]

    valid_records = []
    row_errors = []

    f = io.StringIO(content.strip())
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        return [], [RowErrorDetail(row_index=0, error_message="Empty CSV file or missing headers")]

    headers_lower = {h.strip().lower(): h for h in reader.fieldnames if h}

    def get_val(row_dict: Dict[str, Any], canonical_key: str) -> Optional[str]:
        if column_mapping and canonical_key in column_mapping:
            target_hdr = column_mapping[canonical_key]
            return row_dict.get(target_hdr)
        # Fallback to case-insensitive header match
        for h_low, h_orig in headers_lower.items():
            if h_low == canonical_key.lower():
                return row_dict.get(h_orig)
        return None

    for idx, row in enumerate(reader, start=1):
        raw_title = get_val(row, "title")
        if not raw_title or not raw_title.strip():
            row_errors.append(
                RowErrorDetail(
                    row_index=idx,
                    error_message="Missing required field 'title'",
                    raw_snippet=str(dict(row))[:200],
                )
            )
            continue

        doi = get_val(row, "doi")
        authors_val = get_val(row, "authors")
        authors = []
        if authors_val:
            s_auth = authors_val.strip()
            if s_auth.startswith("[") and s_auth.endswith("]"):
                try:
                    authors = json.loads(s_auth)
                except Exception:
                    authors = [a.strip() for a in s_auth.strip("[]").split(",") if a.strip()]
            elif ";" in s_auth:
                authors = [a.strip() for a in s_auth.split(";") if a.strip()]
            else:
                authors = [a.strip() for a in s_auth.split(",") if a.strip()]

        year_val = get_val(row, "year")
        year = None
        if year_val:
            try:
                year = int(float(str(year_val).strip()))
            except Exception:
                year = None

        venue = get_val(row, "venue") or get_val(row, "journal") or ""
        doc_type = get_val(row, "doc_type") or "other"
        abstract = get_val(row, "abstract") or ""
        url = get_val(row, "url") or ""

        keywords_val = get_val(row, "keywords")
        keywords = []
        if keywords_val:
            s_kw = keywords_val.strip()
            if s_kw.startswith("[") and s_kw.endswith("]"):
                try:
                    keywords = json.loads(s_kw)
                except Exception:
                    keywords = [k.strip() for k in s_kw.strip("[]").split(",") if k.strip()]
            else:
                keywords = [k.strip() for k in s_kw.split(";") if k.strip()]

        valid_records.append({
            "title": raw_title.strip(),
            "doi": doi.strip() if doi else None,
            "authors": authors,
            "year": year,
            "venue": venue.strip(),
            "doc_type": doc_type.strip(),
            "abstract": abstract.strip(),
            "keywords": keywords,
            "url": url.strip(),
            "raw_bibtex_key": get_val(row, "raw_bibtex_key") or "",
        })

    return valid_records, row_errors


def parse_ris_records(content: str) -> Tuple[List[Dict[str, Any]], List[RowErrorDetail]]:
    """Robust RFC-compliant RIS parser."""
    valid_records = []
    row_errors = []

    records_raw = content.split("ER  -")
    for idx, block in enumerate(records_raw, start=1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        item: Dict[str, Any] = {
            "title": "",
            "doi": None,
            "authors": [],
            "year": None,
            "venue": "",
            "doc_type": "other",
            "abstract": "",
            "keywords": [],
            "url": "",
        }

        for line in lines:
            if len(line) >= 6 and line[2:6] == "  - ":
                tag = line[:2].upper()
                val = line[6:].strip()
                if tag in ("TI", "T1"):
                    item["title"] = val
                elif tag in ("AU", "A1"):
                    item["authors"].append(val)
                elif tag in ("PY", "Y1"):
                    try:
                        item["year"] = int(val[:4])
                    except Exception:
                        pass
                elif tag == "DO":
                    item["doi"] = val
                elif tag in ("T2", "JF", "JO"):
                    item["venue"] = val
                elif tag in ("AB", "N2"):
                    item["abstract"] = val
                elif tag == "KW":
                    item["keywords"].append(val)
                elif tag in ("UR", "LK"):
                    item["url"] = val
                elif tag == "TY":
                    ty_map = {"JOUR": "journal", "CONF": "conference", "BOOK": "book", "CHAP": "chapter"}
                    item["doc_type"] = ty_map.get(val, "other")

        if not item["title"]:
            row_errors.append(
                RowErrorDetail(
                    row_index=idx,
                    error_message="Missing required RIS title field (TI or T1)",
                    raw_snippet=block[:200],
                )
            )
            continue

        valid_records.append(item)

    return valid_records, row_errors


def parse_bibtex_records(content: str) -> Tuple[List[Dict[str, Any]], List[RowErrorDetail]]:
    """BibTeX parser using bibtexparser library."""
    import bibtexparser
    valid_records = []
    row_errors = []

    try:
        bib_db = bibtexparser.loads(content)
    except Exception as e:
        return [], [RowErrorDetail(row_index=0, error_message=f"BibTeX parse error: {e}")]

    for idx, entry in enumerate(bib_db.entries, start=1):
        title = entry.get("title", "").strip().strip("{}")
        if not title:
            row_errors.append(
                RowErrorDetail(
                    row_index=idx,
                    error_message="Missing required field 'title' in BibTeX entry",
                    raw_snippet=str(entry)[:200],
                )
            )
            continue

        authors_raw = entry.get("author", "")
        authors = [a.strip().strip("{}") for a in authors_raw.split(" and ") if a.strip()]

        year = None
        if "year" in entry:
            try:
                year = int(entry["year"].strip().strip("{}")[:4])
            except Exception:
                pass

        venue = entry.get("journal") or entry.get("booktitle") or ""
        venue = venue.strip().strip("{}")

        valid_records.append({
            "title": title,
            "doi": entry.get("doi", "").strip() or None,
            "authors": authors,
            "year": year,
            "venue": venue,
            "doc_type": entry.get("ENTRYTYPE", "article"),
            "abstract": entry.get("abstract", "").strip().strip("{}"),
            "keywords": [k.strip() for k in entry.get("keywords", "").split(",") if k.strip()],
            "url": entry.get("url", "").strip(),
            "raw_bibtex_key": entry.get("ID", ""),
        })

    return valid_records, row_errors


class InterchangeService:
    def __init__(self, repo: Optional[ResearchRepository] = None):
        self.repo = repo or ResearchRepository()
        self.acq = AcquisitionService(self.repo)
        self._previews: Dict[str, Dict[str, Any]] = {}

    def preview_import(
        self,
        file_content: str,
        file_format: str,
        csv_mapping: Optional[Dict[str, str]] = None,
    ) -> ImportPreviewResponse:
        """
        Parses import file without modifying corpus.
        Validates max size (20 MiB) and max records (10000).
        Expires in 30 minutes.
        """
        # Validate size: 20 MiB
        byte_len = len(file_content.encode("utf-8"))
        if byte_len > 20 * 1024 * 1024:
            raise ScopeValidationError("Import file exceeds maximum allowed size of 20 MiB")

        file_hash = hashlib.sha256(file_content.encode("utf-8")).hexdigest()
        fmt = file_format.lower()

        if fmt == "csv":
            valid_items, row_errors = parse_csv_records(file_content, csv_mapping)
        elif fmt == "ris":
            valid_items, row_errors = parse_ris_records(file_content)
        elif fmt in ("bib", "bibtex"):
            valid_items, row_errors = parse_bibtex_records(file_content)
        else:
            raise ScopeValidationError(f"Unsupported import format: '{file_format}'")

        total_parsed = len(valid_items) + len(row_errors)
        if total_parsed > 10000:
            raise ScopeValidationError(f"Import exceeds maximum record limit of 10000 (found {total_parsed})")

        preview_id = str(uuid.uuid4())
        expires_at = datetime.fromtimestamp(time.time() + 1800, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        self._previews[preview_id] = {
            "file_hash": file_hash,
            "expires_timestamp": time.time() + 1800,
            "valid_items": valid_items,
            "row_errors": row_errors,
        }

        return ImportPreviewResponse(
            preview_id=preview_id,
            file_hash=file_hash,
            total_parsed=total_parsed,
            valid_count=len(valid_items),
            invalid_count=len(row_errors),
            row_errors=row_errors,
            preview_items=valid_items[:5],
            expires_at=expires_at,
        )

    def commit_import(
        self,
        project_id: str,
        preview_id: str,
        file_hash: str,
        idempotency_key: str,
        actor_label: str = "",
    ) -> ImportCommitResponse:
        """
        Commits previously previewed import into project_id.
        Applies Section 5 identity and dedup rules.
        """
        preview = self._previews.get(preview_id)
        if not preview or preview["expires_timestamp"] < time.time() or preview["file_hash"] != file_hash:
            raise PreviewExpiredOrChangedError(preview_id)

        valid_items = preview["valid_items"]
        row_errors = preview["row_errors"]

        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "COMMIT_IMPORT", idempotency_key, {"preview_id": preview_id, "hash": file_hash}
            )
            if cached:
                return ImportCommitResponse(**cached)

            self.repo.check_project_active(conn, project_id)

            run_id = str(uuid.uuid4())
            now = utc_now_iso()

            conn.execute(
                """
                INSERT INTO acquisition_runs (
                    run_id, project_id, kind, status, request_json, started_at, finished_at,
                    reported_total, observed_count, unique_count, stop_reason
                ) VALUES (?, ?, 'IMPORT', 'RUNNING', ?, ?, ?, ?, 0, 0, NULL)
                """,
                (run_id, project_id, json.dumps({"source": "file_import", "preview_id": preview_id}), now, now, len(valid_items)),
            )

            # Ingest all valid items
            imported_count = self.acq.ingest_batch_of_papers(conn, project_id, run_id, valid_items, enrich=False)

            cur = conn.cursor()
            cur.execute("SELECT COUNT(DISTINCT publication_id) FROM source_observations WHERE run_id = ?", (run_id,))
            unique_count = cur.fetchone()[0]

            conn.execute(
                """
                UPDATE acquisition_runs
                SET status = 'COMPLETED', observed_count = ?, unique_count = ?
                WHERE run_id = ?
                """,
                (imported_count, unique_count, run_id),
            )

            result = {
                "run_id": run_id,
                "imported_count": imported_count,
                "rejected_count": len(row_errors),
                "rejected_report": [r.model_dump() for r in row_errors],
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="ACQUISITION_RUN",
                entity_id=run_id,
                action="IMPORT_COMMITTED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before=None,
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "COMMIT_IMPORT", idempotency_key, {"preview_id": preview_id, "hash": file_hash}, result
            )
            conn.commit()

        # Clean preview cache
        self._previews.pop(preview_id, None)
        return ImportCommitResponse(**result)

    # --- Export ---

    def export_project(
        self,
        project_id: str,
        scope: ExportScope,
        export_format: ExportFormat,
        collection_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exports bibliography (BIB, RIS, CSV) or complete PROJECT_JSON.
        Excludes credentials, cookies, tokens, private paths.
        """
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,))
            proj = cur.fetchone()
            if not proj:
                raise NotFoundError("Project", project_id)

            if export_format == ExportFormat.PROJECT_JSON:
                if scope != ExportScope.ALL:
                    raise ScopeValidationError("PROJECT_JSON export requires scope = 'ALL'")
                return self._export_project_json(conn, proj)

            # Bibliographic export
            where_sql = "pp.project_id = ?"
            params: List[Any] = [project_id]

            if scope == ExportScope.COLLECTION:
                if not collection_id:
                    raise ScopeValidationError("COLLECTION export requires collection_id")
                where_sql += " AND p.publication_id IN (SELECT publication_id FROM collection_members WHERE collection_id = ? AND project_id = ?)"
                params.extend([collection_id, project_id])

            cur.execute(
                f"""
                SELECT p.* FROM project_publications pp
                JOIN publications p ON pp.publication_id = p.publication_id
                WHERE {where_sql}
                ORDER BY pp.added_at ASC, p.publication_id ASC
                """,
                params,
            )
            pubs = cur.fetchall()

            if export_format == ExportFormat.BIB:
                return self._export_to_bibtex(pubs, proj["name"])
            elif export_format == ExportFormat.RIS:
                return self._export_to_ris(pubs, proj["name"])
            elif export_format == ExportFormat.CSV:
                return self._export_to_csv(pubs, proj["name"])
            else:
                raise ScopeValidationError(f"Unsupported format: {export_format}")

    def _export_to_csv(self, pubs: List[sqlite3.Row], project_name: str) -> Dict[str, Any]:
        output = io.StringIO()
        fieldnames = ["title", "authors", "year", "doi", "venue", "doc_type", "abstract", "keywords", "url"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()

        for p in pubs:
            try:
                auth_obj = json.loads(p["authors_json"]) if p["authors_json"] else []
                auth_str = json.dumps(auth_obj, ensure_ascii=False)
            except Exception:
                auth_str = p["authors_json"] or "[]"

            try:
                kw_obj = json.loads(p["keywords_json"]) if p["keywords_json"] else []
                kw_str = json.dumps(kw_obj, ensure_ascii=False)
            except Exception:
                kw_str = p["keywords_json"] or "[]"

            writer.writerow({
                "title": p["title"],
                "authors": auth_str,
                "year": p["year"],
                "doi": p["doi"] or "",
                "venue": p["venue"] or "",
                "doc_type": p["doc_type"],
                "abstract": p["abstract"],
                "keywords": kw_str,
                "url": p["url"],
            })

        unrepresented = [
            {"field": "annotations", "reason": "Notes and textual evidence cannot be represented in plain CSV"}
        ]
        return {
            "format": "CSV",
            "content": output.getvalue(),
            "filename": f"export_{normalize_title(project_name)[:30]}.csv",
            "record_count": len(pubs),
            "unrepresented_report": unrepresented,
        }

    def _export_to_ris(self, pubs: List[sqlite3.Row], project_name: str) -> Dict[str, Any]:
        lines = []
        for p in pubs:
            ty = "JOUR" if "journal" in p["doc_type"].lower() else "CONF"
            lines.append(f"TY  - {ty}")
            lines.append(f"TI  - {p['title']}")
            authors = json.loads(p["authors_json"]) if p["authors_json"] else []
            for a in authors:
                lines.append(f"AU  - {a}")
            if p["year"]:
                lines.append(f"PY  - {p['year']}")
            if p["doi"]:
                lines.append(f"DO  - {p['doi']}")
            if p["venue"]:
                lines.append(f"T2  - {p['venue']}")
            if p["abstract"]:
                lines.append(f"AB  - {p['abstract']}")
            keywords = json.loads(p["keywords_json"]) if p["keywords_json"] else []
            for k in keywords:
                lines.append(f"KW  - {k}")
            if p["url"]:
                lines.append(f"UR  - {p['url']}")
            lines.append("ER  - \n")

        content = "\n".join(lines)
        return {
            "format": "RIS",
            "content": content,
            "filename": f"export_{normalize_title(project_name)[:30]}.ris",
            "record_count": len(pubs),
            "unrepresented_report": [{"field": "annotations", "reason": "Notes/evidence not supported in RIS"}],
        }

    def _export_to_bibtex(self, pubs: List[sqlite3.Row], project_name: str) -> Dict[str, Any]:
        entries = []
        for p in pubs:
            key = p["raw_bibtex_key"] or f"ref_{p['publication_id'][:8]}"
            authors = json.loads(p["authors_json"]) if p["authors_json"] else []
            author_str = " and ".join(authors) if authors else "Anon."
            year_str = str(p["year"]) if p["year"] else ""
            doi_str = p["doi"] or ""
            venue_str = p["venue"] or ""

            entry = f"@article{{{key},\n"
            entry += f"  title = {{{p['title']}}},\n"
            entry += f"  author = {{{author_str}}},\n"
            if year_str:
                entry += f"  year = {{{year_str}}},\n"
            if venue_str:
                entry += f"  journal = {{{venue_str}}},\n"
            if doi_str:
                entry += f"  doi = {{{doi_str}}},\n"
            entry += "}\n"
            entries.append(entry)

        content = "\n".join(entries)
        return {
            "format": "BIB",
            "content": content,
            "filename": f"export_{normalize_title(project_name)[:30]}.bib",
            "record_count": len(pubs),
            "unrepresented_report": [{"field": "annotations", "reason": "Notes/evidence not supported in BibTeX"}],
        }

    def _export_project_json(self, conn: sqlite3.Connection, proj: sqlite3.Row) -> Dict[str, Any]:
        """
        Exports clean, sanitized PROJECT_JSON (schema_version 1).
        Excludes cookies, credentials, tokens, auth headers, and private local paths.
        """
        pid = proj["project_id"]
        cur = conn.cursor()

        # Questions
        cur.execute("SELECT * FROM research_questions WHERE project_id = ? ORDER BY position ASC", (pid,))
        questions = [dict(r) for r in cur.fetchall()]

        # Objectives
        cur.execute("SELECT * FROM research_objectives WHERE project_id = ? ORDER BY position ASC", (pid,))
        objectives = [dict(r) for r in cur.fetchall()]

        # Publications & memberships
        cur.execute(
            """
            SELECT p.*, pp.reading_status, pp.added_at, pp.revision as membership_revision
            FROM project_publications pp
            JOIN publications p ON pp.publication_id = p.publication_id
            WHERE pp.project_id = ?
            """,
            (pid,),
        )
        pub_rows = cur.fetchall()
        publications = []
        memberships = []
        for r in pub_rows:
            d = dict(r)
            m_rev = d.pop("membership_revision")
            r_status = d.pop("reading_status")
            a_at = d.pop("added_at")
            publications.append(d)
            memberships.append({
                "project_id": pid,
                "publication_id": r["publication_id"],
                "reading_status": r_status,
                "added_at": a_at,
                "revision": m_rev,
            })

        # Collections
        cur.execute("SELECT * FROM collections WHERE project_id = ?", (pid,))
        collections = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM collection_members WHERE project_id = ?", (pid,))
        collection_members = [dict(r) for r in cur.fetchall()]

        # Tags
        cur.execute("SELECT * FROM tags WHERE project_id = ?", (pid,))
        tags = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM publication_tags WHERE project_id = ?", (pid,))
        publication_tags = [dict(r) for r in cur.fetchall()]

        # Annotations
        cur.execute("SELECT * FROM annotations WHERE project_id = ?", (pid,))
        annotations = [dict(r) for r in cur.fetchall()]

        # Acquisition runs & sanitized observations
        cur.execute("SELECT * FROM acquisition_runs WHERE project_id = ?", (pid,))
        runs = []
        for r in cur.fetchall():
            rd = dict(r)
            # Sanitize request_json
            try:
                rj = json.loads(rd["request_json"])
                for secret_k in ["api_key", "password", "token", "cookies", "headers"]:
                    rj.pop(secret_k, None)
                rd["request_json"] = json.dumps(rj)
            except Exception:
                pass
            runs.append(rd)

        cur.execute(
            """
            SELECT so.* FROM source_observations so
            JOIN acquisition_runs ar ON so.run_id = ar.run_id
            WHERE ar.project_id = ?
            """,
            (pid,),
        )
        observations = []
        for r in cur.fetchall():
            od = dict(r)
            # Ensure raw_json is sanitized
            try:
                raw_d = json.loads(od["raw_json"])
                for secret_k in ["api_key", "password", "token", "cookies", "headers"]:
                    raw_d.pop(secret_k, None)
                od["raw_json"] = json.dumps(raw_d)
            except Exception:
                pass
            observations.append(od)

        # Events
        cur.execute("SELECT * FROM research_events WHERE project_id = ? ORDER BY created_at ASC", (pid,))
        events = [dict(r) for r in cur.fetchall()]

        data = {
            "schema_version": 1,
            "exported_at": utc_now_iso(),
            "project": dict(proj),
            "questions": questions,
            "objectives": objectives,
            "publications": publications,
            "memberships": memberships,
            "collections": collections,
            "collection_members": collection_members,
            "tags": tags,
            "publication_tags": publication_tags,
            "annotations": annotations,
            "runs": runs,
            "observations": observations,
            "events": events,
        }

        return {
            "format": "PROJECT_JSON",
            "content": json.dumps(data, indent=2),
            "filename": f"project_{normalize_title(proj['name'])[:30]}.json",
            "record_count": len(publications),
            "unrepresented_report": [],
        }

    # --- Restore ---

    def preview_restore(self, project_json_content: str) -> RestorePreviewResponse:
        """
        Validates schema_version, reference integrity, and counts before restore.
        """
        try:
            data = json.loads(project_json_content)
        except Exception as e:
            raise RestoreValidationError(f"Invalid JSON format: {e}")

        if data.get("schema_version") != 1:
            raise RestoreValidationError(f"Unsupported schema_version '{data.get('schema_version')}'. Expected 1.")

        project_data = data.get("project")
        if not project_data or not project_data.get("name"):
            raise RestoreValidationError("Missing project metadata in export file")

        # Validate reference integrity
        pub_ids = {p["publication_id"] for p in data.get("publications", [])}
        q_ids = {q["question_id"] for q in data.get("questions", [])}
        c_ids = {c["collection_id"] for c in data.get("collections", [])}
        t_ids = {t["tag_id"] for t in data.get("tags", [])}

        # Check memberships
        for m in data.get("memberships", []):
            if m["publication_id"] not in pub_ids:
                raise RestoreValidationError(f"Broken reference: membership references missing publication '{m['publication_id']}'")

        # Check collection members
        for cm in data.get("collection_members", []):
            if cm["collection_id"] not in c_ids or cm["publication_id"] not in pub_ids:
                raise RestoreValidationError("Broken reference in collection members")

        # Check publication tags
        for pt in data.get("publication_tags", []):
            if pt["tag_id"] not in t_ids or pt["publication_id"] not in pub_ids:
                raise RestoreValidationError("Broken reference in publication tags")

        # Check annotations
        for ann in data.get("annotations", []):
            if ann["publication_id"] not in pub_ids:
                raise RestoreValidationError(f"Broken reference: annotation references missing publication '{ann['publication_id']}'")
            if ann.get("question_id") and ann["question_id"] not in q_ids:
                raise RestoreValidationError(f"Broken reference: annotation references missing question '{ann['question_id']}'")

        file_hash = hashlib.sha256(project_json_content.encode("utf-8")).hexdigest()
        preview_id = str(uuid.uuid4())
        expires_at = datetime.fromtimestamp(time.time() + 1800, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        counts = {
            "questions": len(data.get("questions", [])),
            "objectives": len(data.get("objectives", [])),
            "publications": len(data.get("publications", [])),
            "collections": len(data.get("collections", [])),
            "tags": len(data.get("tags", [])),
            "annotations": len(data.get("annotations", [])),
        }

        self._previews[preview_id] = {
            "file_hash": file_hash,
            "expires_timestamp": time.time() + 1800,
            "data": data,
        }

        return RestorePreviewResponse(
            preview_id=preview_id,
            file_hash=file_hash,
            schema_version=1,
            project_name=project_data["name"],
            counts=counts,
            expires_at=expires_at,
        )

    def commit_restore(
        self,
        preview_id: str,
        file_hash: str,
        idempotency_key: str,
        actor_label: str = "",
    ) -> RestoreCommitResponse:
        """
        Restores project atomically. Always creates a NEW project.
        Remaps IDs, preserves dates and actor types of annotations, and adds event RESTORED.
        """
        preview = self._previews.get(preview_id)
        if not preview or preview["expires_timestamp"] < time.time() or preview["file_hash"] != file_hash:
            raise PreviewExpiredOrChangedError(preview_id)

        data = preview["data"]

        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, "GLOBAL", "RESTORE_PROJECT", idempotency_key, {"preview_id": preview_id, "hash": file_hash}
            )
            if cached:
                return RestoreCommitResponse(**cached)

            new_project_id = str(uuid.uuid4())
            now = utc_now_iso()
            cur = conn.cursor()

            # ID mapping tables
            id_map: Dict[str, Dict[str, str]] = {
                "publications": {},
                "questions": {},
                "objectives": {},
                "collections": {},
                "tags": {},
                "annotations": {},
                "runs": {},
            }

            orig_proj = data["project"]
            new_proj_name = f"{orig_proj['name']} (Restored)"

            conn.execute(
                """
                INSERT INTO research_projects (
                    project_id, name, description, research_type, archived, created_at, updated_at, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    new_project_id,
                    new_proj_name,
                    orig_proj.get("description", ""),
                    orig_proj.get("research_type", ""),
                    orig_proj.get("archived", 0),
                    now,
                    now,
                ),
            )

            # Recreate questions
            for q in data.get("questions", []):
                old_qid = q["question_id"]
                new_qid = str(uuid.uuid4())
                id_map["questions"][old_qid] = new_qid
                conn.execute(
                    """
                    INSERT INTO research_questions (question_id, project_id, text, position, revision)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (new_qid, new_project_id, q["text"], q["position"]),
                )

            # Recreate objectives
            for o in data.get("objectives", []):
                old_oid = o["objective_id"]
                new_oid = str(uuid.uuid4())
                id_map["objectives"][old_oid] = new_oid
                conn.execute(
                    """
                    INSERT INTO research_objectives (objective_id, project_id, text, position, revision)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (new_oid, new_project_id, o["text"], o["position"]),
                )

            # Recreate publications (reuse by DOI if compatible)
            for p in data.get("publications", []):
                old_pid = p["publication_id"]
                doi = normalize_doi(p.get("doi"))
                matched_id = None
                if doi:
                    cur.execute("SELECT publication_id FROM publications WHERE doi = ?", (doi,))
                    found = cur.fetchone()
                    if found:
                        matched_id = found[0]

                if matched_id:
                    id_map["publications"][old_pid] = matched_id
                else:
                    new_pub_id = str(uuid.uuid4())
                    id_map["publications"][old_pid] = new_pub_id
                    conn.execute(
                        """
                        INSERT INTO publications (
                            publication_id, doi, title, normalized_title, authors_json, year,
                            venue, doc_type, abstract, keywords_json, url, raw_bibtex_key,
                            created_at, updated_at, revision
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            new_pub_id,
                            doi,
                            p["title"],
                            normalize_title(p["title"]),
                            p["authors_json"],
                            p.get("year"),
                            p.get("venue"),
                            p.get("doc_type", "other"),
                            p.get("abstract", ""),
                            p.get("keywords_json", "[]"),
                            p.get("url", ""),
                            p.get("raw_bibtex_key", ""),
                            p.get("created_at", now),
                            now,
                        ),
                    )

            # Recreate memberships
            for m in data.get("memberships", []):
                real_pub_id = id_map["publications"][m["publication_id"]]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO project_publications (
                        project_id, publication_id, reading_status, added_at, revision
                    ) VALUES (?, ?, ?, ?, 1)
                    """,
                    (new_project_id, real_pub_id, m["reading_status"], m.get("added_at", now)),
                )

            # Recreate collections
            for c in data.get("collections", []):
                old_cid = c["collection_id"]
                new_cid = str(uuid.uuid4())
                id_map["collections"][old_cid] = new_cid
                conn.execute(
                    """
                    INSERT INTO collections (collection_id, project_id, name, name_key, revision)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (new_cid, new_project_id, c["name"], c["name_key"]),
                )

            # Recreate collection members
            for cm in data.get("collection_members", []):
                real_cid = id_map["collections"][cm["collection_id"]]
                real_pub_id = id_map["publications"][cm["publication_id"]]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO collection_members (collection_id, project_id, publication_id)
                    VALUES (?, ?, ?)
                    """,
                    (real_cid, new_project_id, real_pub_id),
                )

            # Recreate tags
            for t in data.get("tags", []):
                old_tid = t["tag_id"]
                new_tid = str(uuid.uuid4())
                id_map["tags"][old_tid] = new_tid
                conn.execute(
                    """
                    INSERT INTO tags (tag_id, project_id, name, name_key, revision)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (new_tid, new_project_id, t["name"], t["name_key"]),
                )

            # Recreate publication tags
            for pt in data.get("publication_tags", []):
                real_tid = id_map["tags"][pt["tag_id"]]
                real_pub_id = id_map["publications"][pt["publication_id"]]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO publication_tags (tag_id, project_id, publication_id)
                    VALUES (?, ?, ?)
                    """,
                    (real_tid, new_project_id, real_pub_id),
                )

            # Recreate annotations
            for ann in data.get("annotations", []):
                old_ann_id = ann["annotation_id"]
                new_ann_id = str(uuid.uuid4())
                id_map["annotations"][old_ann_id] = new_ann_id
                real_pub_id = id_map["publications"][ann["publication_id"]]
                real_qid = id_map["questions"].get(ann["question_id"]) if ann.get("question_id") else None

                conn.execute(
                    """
                    INSERT INTO annotations (
                        annotation_id, project_id, publication_id, kind, body, source_kind,
                        source_url, locator, question_id, actor_type, actor_label,
                        created_at, updated_at, revision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        new_ann_id,
                        new_project_id,
                        real_pub_id,
                        ann["kind"],
                        ann["body"],
                        ann["source_kind"],
                        ann.get("source_url"),
                        ann.get("locator"),
                        real_qid,
                        ann.get("actor_type", "HUMAN"),
                        ann.get("actor_label", ""),
                        ann.get("created_at", now),
                        now,
                    ),
                )

            # Recreate runs
            for r in data.get("runs", []):
                old_rid = r["run_id"]
                new_rid = str(uuid.uuid4())
                id_map["runs"][old_rid] = new_rid
                conn.execute(
                    """
                    INSERT INTO acquisition_runs (
                        run_id, project_id, kind, status, request_json, started_at, finished_at,
                        reported_total, observed_count, unique_count, stop_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_rid,
                        new_project_id,
                        r["kind"],
                        r["status"],
                        r["request_json"],
                        r["started_at"],
                        r.get("finished_at"),
                        r.get("reported_total"),
                        r.get("observed_count", 0),
                        r.get("unique_count", 0),
                        r.get("stop_reason"),
                    ),
                )

            # Add RESTORED event
            self.repo.log_event(
                conn,
                project_id=new_project_id,
                entity_type="PROJECT",
                entity_id=new_project_id,
                action="RESTORED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before=None,
                after={"original_project_id": orig_proj["project_id"], "new_project_id": new_project_id},
            )

            result = {
                "new_project_id": new_project_id,
                "id_mapping": id_map,
                "restored_at": now,
            }

            self.repo.record_receipt(
                conn, "GLOBAL", "RESTORE_PROJECT", idempotency_key, {"preview_id": preview_id, "hash": file_hash}, result
            )
            conn.commit()

        self._previews.pop(preview_id, None)
        return RestoreCommitResponse(**result)
