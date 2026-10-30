"""
Library, Project Memberships, Organization & Manual Publication Merge Service.
Implements Sections 4, 5, 8: Filtering, reading status, collections/tags, dedup rules, and transactional manual merge.
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import uuid
import json
import sqlite3
import unicodedata

from core.research.repository import (
    ResearchRepository,
    NotFoundError,
    RevisionConflictError,
    ScopeValidationError,
    resolve_actor_type,
)
from core.research.models import (
    ReadingStatus,
    UpdateReadingStatusRequest,
    SetOrganizationRequest,
    MergePublicationsRequest,
    normalize_name_key,
)
from core.migrations.runner import utc_now_iso


class LibraryService:
    def __init__(self, repo: Optional[ResearchRepository] = None):
        self.repo = repo or ResearchRepository()

    def list_publications(
        self,
        project_id: str,
        q: Optional[str] = None,
        reading_status: Optional[str] = None,
        collection_id: Optional[str] = None,
        tag_id: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        with self.repo.get_connection() as conn:
            # Check project exists
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM research_projects WHERE project_id = ?", (project_id,))
            if not cur.fetchone():
                raise NotFoundError("Project", project_id)

            where_clauses = ["pp.project_id = ?"]
            params: List[Any] = [project_id]

            if q and q.strip():
                clean_q = f"%{q.strip().casefold()}%"
                where_clauses.append("(LOWER(p.title) LIKE ? OR LOWER(p.normalized_title) LIKE ?)")
                params.extend([clean_q, clean_q])

            if reading_status and reading_status.strip():
                where_clauses.append("pp.reading_status = ?")
                params.append(reading_status.strip().upper())

            if collection_id and collection_id.strip():
                where_clauses.append("""
                    p.publication_id IN (
                        SELECT publication_id FROM collection_members
                        WHERE collection_id = ? AND project_id = ?
                    )
                """)
                params.extend([collection_id.strip(), project_id])

            if tag_id and tag_id.strip():
                where_clauses.append("""
                    p.publication_id IN (
                        SELECT publication_id FROM publication_tags
                        WHERE tag_id = ? AND project_id = ?
                    )
                """)
                params.extend([tag_id.strip(), project_id])

            where_sql = " AND ".join(where_clauses)

            # Count total
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM project_publications pp
                JOIN publications p ON pp.publication_id = p.publication_id
                WHERE {where_sql}
                """,
                params,
            )
            total = cur.fetchone()[0]

            # Fetch items
            cur.execute(
                f"""
                SELECT
                    p.publication_id, p.doi, p.title, p.normalized_title, p.authors_json,
                    p.year, p.venue, p.doc_type, p.abstract, p.keywords_json, p.url,
                    p.raw_bibtex_key, p.citation_count, p.created_at, p.updated_at, p.revision,
                    pp.reading_status, pp.added_at
                FROM project_publications pp
                JOIN publications p ON pp.publication_id = p.publication_id
                WHERE {where_sql}
                ORDER BY pp.added_at ASC, p.publication_id ASC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

            items = []
            for r in rows:
                pub_id = r["publication_id"]

                # Collections in this project
                cur.execute(
                    """
                    SELECT c.name FROM collections c
                    JOIN collection_members cm ON c.collection_id = cm.collection_id
                    WHERE cm.project_id = ? AND cm.publication_id = ?
                    ORDER BY c.name ASC
                    """,
                    (project_id, pub_id),
                )
                collections = [cr[0] for cr in cur.fetchall()]

                # Tags in this project
                cur.execute(
                    """
                    SELECT t.name FROM tags t
                    JOIN publication_tags pt ON t.tag_id = pt.tag_id
                    WHERE pt.project_id = ? AND pt.publication_id = ?
                    ORDER BY t.name ASC
                    """,
                    (project_id, pub_id),
                )
                tags = [tr[0] for tr in cur.fetchall()]

                # Sources from source_observations
                cur.execute(
                    """
                    SELECT ar.request_json FROM acquisition_runs ar
                    JOIN source_observations so ON ar.run_id = so.run_id
                    WHERE so.publication_id = ?
                    """,
                    (pub_id,),
                )
                sources_set = set()
                for obs in cur.fetchall():
                    try:
                        req_data = json.loads(obs[0])
                        db_name = req_data.get("database") or req_data.get("source")
                        if db_name:
                            sources_set.add(db_name.lower())
                    except Exception:
                        pass
                sources = sorted(list(sources_set)) if sources_set else ["academic"]

                try:
                    authors = json.loads(r["authors_json"])
                except Exception:
                    authors = []

                try:
                    keywords = json.loads(r["keywords_json"])
                except Exception:
                    keywords = []

                items.append({
                    "publication_id": pub_id,
                    "doi": r["doi"],
                    "title": r["title"],
                    "normalized_title": r["normalized_title"],
                    "authors": authors,
                    "year": r["year"],
                    "venue": r["venue"],
                    "doc_type": r["doc_type"],
                    "abstract": r["abstract"],
                    "keywords": keywords,
                    "url": r["url"],
                    "raw_bibtex_key": r["raw_bibtex_key"],
                    "citation_count": r["citation_count"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "revision": r["revision"],
                    "reading_status": r["reading_status"],
                    "added_at": r["added_at"],
                    "collections": collections,
                    "tags": tags,
                    "sources": sources,
                })

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def get_publication(self, project_id: str, publication_id: str) -> Dict[str, Any]:
        pubs = self.list_publications(project_id=project_id, limit=1, offset=0)
        # Fetch directly
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    p.publication_id, p.doi, p.title, p.normalized_title, p.authors_json,
                    p.year, p.venue, p.doc_type, p.abstract, p.keywords_json, p.url,
                    p.raw_bibtex_key, p.citation_count, p.created_at, p.updated_at, p.revision,
                    pp.reading_status, pp.added_at
                FROM project_publications pp
                JOIN publications p ON pp.publication_id = p.publication_id
                WHERE pp.project_id = ? AND pp.publication_id = ?
                """,
                (project_id, publication_id),
            )
            r = cur.fetchone()
            if not r:
                # Check if publication exists globally or has alias
                cur.execute("SELECT publication_id FROM publication_aliases WHERE old_id = ?", (publication_id,))
                alias = cur.fetchone()
                if alias:
                    return self.get_publication(project_id, alias[0])
                raise NotFoundError("Publication in project", publication_id)

            # Collections
            cur.execute(
                """
                SELECT c.name FROM collections c
                JOIN collection_members cm ON c.collection_id = cm.collection_id
                WHERE cm.project_id = ? AND cm.publication_id = ?
                """,
                (project_id, publication_id),
            )
            collections = [cr[0] for cr in cur.fetchall()]

            # Tags
            cur.execute(
                """
                SELECT t.name FROM tags t
                JOIN publication_tags pt ON t.tag_id = pt.tag_id
                WHERE pt.project_id = ? AND pt.publication_id = ?
                """,
                (project_id, publication_id),
            )
            tags = [tr[0] for tr in cur.fetchall()]

            # Sources
            cur.execute(
                """
                SELECT ar.request_json FROM acquisition_runs ar
                JOIN source_observations so ON ar.run_id = so.run_id
                WHERE so.publication_id = ?
                """,
                (publication_id,),
            )
            sources_set = set()
            for obs in cur.fetchall():
                try:
                    req_data = json.loads(obs[0])
                    db_name = req_data.get("database") or req_data.get("source")
                    if db_name:
                        sources_set.add(db_name.lower())
                except Exception:
                    pass
            sources = sorted(list(sources_set)) if sources_set else ["academic"]

            return {
                "publication_id": r["publication_id"],
                "doi": r["doi"],
                "title": r["title"],
                "normalized_title": r["normalized_title"],
                "authors": json.loads(r["authors_json"]) if r["authors_json"] else [],
                "year": r["year"],
                "venue": r["venue"],
                "doc_type": r["doc_type"],
                "abstract": r["abstract"],
                "keywords": json.loads(r["keywords_json"]) if r["keywords_json"] else [],
                "url": r["url"],
                "raw_bibtex_key": r["raw_bibtex_key"],
                "citation_count": r["citation_count"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "revision": r["revision"],
                "reading_status": r["reading_status"],
                "added_at": r["added_at"],
                "collections": collections,
                "tags": tags,
                "sources": sources,
            }

    def update_reading_status(
        self, project_id: str, publication_id: str, req: UpdateReadingStatusRequest, actor_label: str = ""
    ) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "UPDATE_READING_STATUS", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            self.repo.check_project_active(conn, project_id)

            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM project_publications WHERE project_id = ? AND publication_id = ?",
                (project_id, publication_id),
            )
            row = cur.fetchone()
            if not row:
                # Check alias
                cur.execute("SELECT publication_id FROM publication_aliases WHERE old_id = ?", (publication_id,))
                alias = cur.fetchone()
                if alias:
                    return self.update_reading_status(project_id, alias[0], req, actor_label)
                raise NotFoundError("ProjectPublication", f"{project_id}/{publication_id}")

            current_rev = row["revision"]
            if req.expected_revision is not None and current_rev != req.expected_revision:
                raise RevisionConflictError(current_rev, req.expected_revision)

            new_rev = current_rev + 1
            new_status = req.reading_status.value

            conn.execute(
                """
                UPDATE project_publications
                SET reading_status = ?, revision = ?
                WHERE project_id = ? AND publication_id = ?
                """,
                (new_status, new_rev, project_id, publication_id),
            )

            result = {
                "project_id": project_id,
                "publication_id": publication_id,
                "reading_status": new_status,
                "revision": new_rev,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="PROJECT_PUBLICATION",
                entity_id=publication_id,
                action="READING_STATUS_CHANGED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before={"reading_status": row["reading_status"], "revision": current_rev},
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "UPDATE_READING_STATUS", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()
            return result

    def set_organization(
        self, project_id: str, req: SetOrganizationRequest, actor_label: str = ""
    ) -> Dict[str, Any]:
        """
        Replaces collections, tags, and assignments atomically in project_id.
        Validates scope: All referenced publications must belong to project_id.
        """
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "SET_ORGANIZATION", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            p = self.repo.check_project_active(conn, project_id)
            current_rev = p["revision"]
            if current_rev != req.expected_revision:
                raise RevisionConflictError(current_rev, req.expected_revision)

            cur = conn.cursor()

            # Verify that all referenced publications belong to this project
            cur.execute("SELECT publication_id FROM project_publications WHERE project_id = ?", (project_id,))
            project_pub_ids = {r[0] for r in cur.fetchall()}

            for cm in req.collection_members:
                if cm.publication_id not in project_pub_ids:
                    raise ScopeValidationError(
                        f"Publication '{cm.publication_id}' does not belong to project '{project_id}'"
                    )

            for pt in req.publication_tags:
                if pt.publication_id not in project_pub_ids:
                    raise ScopeValidationError(
                        f"Publication '{pt.publication_id}' does not belong to project '{project_id}'"
                    )

            # Collections handling
            cur.execute("SELECT collection_id, name_key, revision FROM collections WHERE project_id = ?", (project_id,))
            existing_colls = {r["collection_id"]: (r["name_key"], r["revision"]) for r in cur.fetchall()}

            # Validate collection name_key uniqueness in request
            coll_keys_in_req: Set[str] = set()
            colls_to_save: List[Tuple[str, str, str, int]] = []
            id_to_coll_id: Dict[str, str] = {}

            for c in req.collections:
                n_key = normalize_name_key(c.name)
                if n_key in coll_keys_in_req:
                    raise ScopeValidationError(f"Duplicate collection name key '{n_key}' in request")
                coll_keys_in_req.add(n_key)

                cid = c.collection_id or str(uuid.uuid4())
                old_info = existing_colls.get(cid)
                rev = (old_info[1] + 1) if old_info else 1
                colls_to_save.append((cid, c.name, n_key, rev))
                id_to_coll_id[cid] = cid
                if c.collection_id:
                    id_to_coll_id[c.collection_id] = cid

            # Tags handling
            cur.execute("SELECT tag_id, name_key, revision FROM tags WHERE project_id = ?", (project_id,))
            existing_tags = {r["tag_id"]: (r["name_key"], r["revision"]) for r in cur.fetchall()}

            tag_keys_in_req: Set[str] = set()
            tags_to_save: List[Tuple[str, str, str, int]] = []
            id_to_tag_id: Dict[str, str] = {}

            for t in req.tags:
                n_key = normalize_name_key(t.name)
                if n_key in tag_keys_in_req:
                    raise ScopeValidationError(f"Duplicate tag name key '{n_key}' in request")
                tag_keys_in_req.add(n_key)

                tid = t.tag_id or str(uuid.uuid4())
                old_info = existing_tags.get(tid)
                rev = (old_info[1] + 1) if old_info else 1
                tags_to_save.append((tid, t.name, n_key, rev))
                id_to_tag_id[tid] = tid
                if t.tag_id:
                    id_to_tag_id[t.tag_id] = tid

            # Validate that assignments point to valid collections/tags in this batch
            for cm in req.collection_members:
                if cm.collection_id not in id_to_coll_id:
                    raise ScopeValidationError(f"Assigned collection_id '{cm.collection_id}' not found in project collections")

            for pt in req.publication_tags:
                if pt.tag_id not in id_to_tag_id:
                    raise ScopeValidationError(f"Assigned tag_id '{pt.tag_id}' not found in project tags")

            # Execute transactional replacement
            # Delete old members and tags
            conn.execute("DELETE FROM collection_members WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM publication_tags WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM collections WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM tags WHERE project_id = ?", (project_id,))

            # Insert collections
            saved_colls = []
            for cid, name, n_key, rev in colls_to_save:
                conn.execute(
                    """
                    INSERT INTO collections (collection_id, project_id, name, name_key, revision)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (cid, project_id, name, n_key, rev),
                )
                saved_colls.append({"collection_id": cid, "name": name, "name_key": n_key, "revision": rev})

            # Insert tags
            saved_tags = []
            for tid, name, n_key, rev in tags_to_save:
                conn.execute(
                    """
                    INSERT INTO tags (tag_id, project_id, name, name_key, revision)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tid, project_id, name, n_key, rev),
                )
                saved_tags.append({"tag_id": tid, "name": name, "name_key": n_key, "revision": rev})

            # Insert collection members
            saved_cms = []
            for cm in req.collection_members:
                real_cid = id_to_coll_id[cm.collection_id]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO collection_members (collection_id, project_id, publication_id)
                    VALUES (?, ?, ?)
                    """,
                    (real_cid, project_id, cm.publication_id),
                )
                saved_cms.append({"collection_id": real_cid, "publication_id": cm.publication_id})

            # Insert publication tags
            saved_pts = []
            for pt in req.publication_tags:
                real_tid = id_to_tag_id[pt.tag_id]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO publication_tags (tag_id, project_id, publication_id)
                    VALUES (?, ?, ?)
                    """,
                    (real_tid, project_id, pt.publication_id),
                )
                saved_pts.append({"tag_id": real_tid, "publication_id": pt.publication_id})

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
                "collections": saved_colls,
                "tags": saved_tags,
                "collection_members": saved_cms,
                "publication_tags": saved_pts,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="PROJECT",
                entity_id=project_id,
                action="ORGANIZATION_UPDATED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before={"revision": current_rev},
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "SET_ORGANIZATION", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()
            return result

    def get_organization(self, project_id: str) -> Dict[str, Any]:
        with self.repo.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT revision FROM research_projects WHERE project_id = ?", (project_id,))
            p = cur.fetchone()
            if not p:
                raise NotFoundError("Project", project_id)

            cur.execute("SELECT * FROM collections WHERE project_id = ? ORDER BY name ASC", (project_id,))
            collections = [
                {"collection_id": r["collection_id"], "name": r["name"], "name_key": r["name_key"], "revision": r["revision"]}
                for r in cur.fetchall()
            ]

            cur.execute("SELECT * FROM tags WHERE project_id = ? ORDER BY name ASC", (project_id,))
            tags = [
                {"tag_id": r["tag_id"], "name": r["name"], "name_key": r["name_key"], "revision": r["revision"]}
                for r in cur.fetchall()
            ]

            cur.execute("SELECT collection_id, publication_id FROM collection_members WHERE project_id = ?", (project_id,))
            cms = [{"collection_id": r["collection_id"], "publication_id": r["publication_id"]} for r in cur.fetchall()]

            cur.execute("SELECT tag_id, publication_id FROM publication_tags WHERE project_id = ?", (project_id,))
            pts = [{"tag_id": r["tag_id"], "publication_id": r["publication_id"]} for r in cur.fetchall()]

            return {
                "project_id": project_id,
                "revision": p["revision"],
                "collections": collections,
                "tags": tags,
                "collection_members": cms,
                "publication_tags": pts,
            }

    def merge_publications(
        self, project_id: str, req: MergePublicationsRequest, actor_label: str = ""
    ) -> Dict[str, Any]:
        """
        Manual publication merge (Section 5 & A07):
        Receives survivor_id and absorbed_id, both present in active project.
        Re-points observations, project memberships, collections, tags, annotations.
        Creates publication_aliases(old_id=absorbed_id, publication_id=survivor_id, alias_type='MERGED').
        Deletes absorbed publication.
        """
        with self.repo.get_connection() as conn:
            cached = self.repo.check_idempotency(
                conn, project_id, "MERGE_PUBLICATIONS", req.idempotency_key, req.model_dump()
            )
            if cached:
                return cached

            self.repo.check_project_active(conn, project_id)

            cur = conn.cursor()
            # Verify survivor in project
            cur.execute(
                "SELECT reading_status FROM project_publications WHERE project_id = ? AND publication_id = ?",
                (project_id, req.survivor_id),
            )
            s_row = cur.fetchone()
            if not s_row:
                raise NotFoundError("Survivor publication in project", req.survivor_id)

            # Verify absorbed in project
            cur.execute(
                "SELECT reading_status FROM project_publications WHERE project_id = ? AND publication_id = ?",
                (project_id, req.absorbed_id),
            )
            a_row = cur.fetchone()
            if not a_row:
                raise NotFoundError("Absorbed publication in project", req.absorbed_id)

            # Find all projects affected by this merge
            cur.execute(
                """
                SELECT DISTINCT project_id FROM project_publications
                WHERE publication_id IN (?, ?)
                """,
                (req.survivor_id, req.absorbed_id),
            )
            affected_projects = [r[0] for r in cur.fetchall()]

            now = utc_now_iso()

            # 1. Ensure survivor is present in project_publications for all affected projects
            # and calculate unified reading status: READ if either is READ, else READING if either is READING, else UNREAD
            final_status_in_active = "UNREAD"
            for pid in affected_projects:
                cur.execute(
                    "SELECT reading_status FROM project_publications WHERE project_id = ? AND publication_id = ?",
                    (pid, req.survivor_id),
                )
                surv_memb = cur.fetchone()
                cur.execute(
                    "SELECT reading_status FROM project_publications WHERE project_id = ? AND publication_id = ?",
                    (pid, req.absorbed_id),
                )
                abs_memb = cur.fetchone()

                s_status = surv_memb["reading_status"] if surv_memb else "UNREAD"
                a_status = abs_memb["reading_status"] if abs_memb else "UNREAD"

                if "READ" in (s_status, a_status):
                    unified_status = "READ"
                elif "READING" in (s_status, a_status):
                    unified_status = "READING"
                else:
                    unified_status = "UNREAD"

                if pid == project_id:
                    final_status_in_active = unified_status

                if surv_memb:
                    conn.execute(
                        "UPDATE project_publications SET reading_status = ?, revision = revision + 1 WHERE project_id = ? AND publication_id = ?",
                        (unified_status, pid, req.survivor_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO project_publications (project_id, publication_id, reading_status, added_at, revision) VALUES (?, ?, ?, ?, 1)",
                        (pid, req.survivor_id, unified_status, now),
                    )

            # 2. Update source_observations
            conn.execute(
                "UPDATE source_observations SET publication_id = ? WHERE publication_id = ?",
                (req.survivor_id, req.absorbed_id),
            )

            # 3. Update annotations (now safe because survivor is guaranteed in project_publications)
            conn.execute(
                "UPDATE annotations SET publication_id = ?, updated_at = ? WHERE publication_id = ?",
                (req.survivor_id, now, req.absorbed_id),
            )

            # 4. Union collection_members (reassign to survivor before deleting absorbed memberships)
            cur.execute("SELECT collection_id, project_id FROM collection_members WHERE publication_id = ?", (req.absorbed_id,))
            abs_colls = cur.fetchall()
            for c_row in abs_colls:
                cid, cpid = c_row["collection_id"], c_row["project_id"]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO collection_members (collection_id, project_id, publication_id)
                    VALUES (?, ?, ?)
                    """,
                    (cid, cpid, req.survivor_id),
                )
            conn.execute("DELETE FROM collection_members WHERE publication_id = ?", (req.absorbed_id,))

            # 5. Union publication_tags (reassign to survivor before deleting absorbed memberships)
            cur.execute("SELECT tag_id, project_id FROM publication_tags WHERE publication_id = ?", (req.absorbed_id,))
            abs_tags = cur.fetchall()
            for t_row in abs_tags:
                tid, tpid = t_row["tag_id"], t_row["project_id"]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO publication_tags (tag_id, project_id, publication_id)
                    VALUES (?, ?, ?)
                    """,
                    (tid, tpid, req.survivor_id),
                )
            conn.execute("DELETE FROM publication_tags WHERE publication_id = ?", (req.absorbed_id,))

            # 6. Delete absorbed from project_publications across all affected projects
            conn.execute(
                "DELETE FROM project_publications WHERE publication_id = ?",
                (req.absorbed_id,),
            )

            # 7. Create alias MERGED
            conn.execute(
                """
                INSERT OR REPLACE INTO publication_aliases (old_id, publication_id, alias_type)
                VALUES (?, ?, 'MERGED')
                """,
                (req.absorbed_id, req.survivor_id),
            )

            # Also update any existing aliases pointing to absorbed_id to point to survivor_id
            conn.execute(
                "UPDATE publication_aliases SET publication_id = ? WHERE publication_id = ?",
                (req.survivor_id, req.absorbed_id),
            )

            # 7. Delete absorbed from publications
            conn.execute("DELETE FROM publications WHERE publication_id = ?", (req.absorbed_id,))

            result = {
                "survivor_id": req.survivor_id,
                "absorbed_id": req.absorbed_id,
                "affected_projects": affected_projects,
                "final_reading_status": final_status_in_active,
                "merged_at": now,
            }

            self.repo.log_event(
                conn,
                project_id=project_id,
                entity_type="PUBLICATION",
                entity_id=req.survivor_id,
                action="PUBLICATIONS_MERGED",
                actor_type=resolve_actor_type(actor_label),
                actor_label=actor_label,
                before={"absorbed_id": req.absorbed_id},
                after=result,
            )

            self.repo.record_receipt(
                conn, project_id, "MERGE_PUBLICATIONS", req.idempotency_key, req.model_dump(), result
            )
            conn.commit()
            return result
