"""
Cross-Database Deduplication Engine for MCPCONECCT.
Implements 2-phase deduplication:
Phase 1: Exact match on canonical normalized DOI.
Phase 2: Fuzzy match on normalized title (Levenshtein/SequenceMatcher >= 0.92) + publication year + 1st author.
"""
from typing import Dict, Any, List, Tuple, Optional
import difflib
import logging
import json

from platforms.base import CanonicalPaper, normalize_doi, normalize_title
from core.db import get_connection

logger = logging.getLogger("mcpconecct.deduplicator")


class CorpusDeduplicator:
    """Performs exact and fuzzy deduplication across multi-database search results."""

    @staticmethod
    def _extract_first_author_lastname(authors: List[str]) -> str:
        """Extracts normalized last name of the first author."""
        if not authors:
            return ""
        first = str(authors[0]).strip().lower()
        if "," in first:
            return first.split(",")[0].strip()
        parts = first.split()
        return parts[-1].strip() if parts else ""

    @classmethod
    def merge_papers(cls, primary: CanonicalPaper, secondary: CanonicalPaper) -> CanonicalPaper:
        """
        Merges two duplicate papers, combining unique metadata and preserving richest fields.
        """
        # 1. Merge sources list preserving order and uniqueness
        combined_sources = list(dict.fromkeys(primary.sources + secondary.sources))
        primary.sources = combined_sources

        # 2. Preserve DOI if secondary has one and primary does not
        if not primary.doi and secondary.doi:
            primary.doi = secondary.doi

        # 3. Preserve longest and richest abstract
        p_abs = primary.abstract or ""
        s_abs = secondary.abstract or ""
        if len(s_abs.strip()) > len(p_abs.strip()):
            primary.abstract = s_abs

        # 4. Preserve most comprehensive authors list
        p_authors = primary.authors or []
        s_authors = secondary.authors or []
        if len(s_authors) > len(p_authors):
            primary.authors = s_authors

        # 5. Union unique keywords
        p_kw = set(k.lower() for k in (primary.keywords or []))
        merged_kw = list(primary.keywords or [])
        for k in (secondary.keywords or []):
            if k.lower() not in p_kw:
                merged_kw.append(k)
                p_kw.add(k.lower())
        primary.keywords = merged_kw

        # 6. Fallback venue and URL
        if not primary.venue and secondary.venue:
            primary.venue = secondary.venue
        if not primary.url and secondary.url:
            primary.url = secondary.url

        # 7. Year fallback
        if primary.year is None and secondary.year is not None:
            primary.year = secondary.year

        # 8. Accumulate duplicate count and enrichment status
        primary.duplicate_count += secondary.duplicate_count
        primary.is_enriched_by_doi = primary.is_enriched_by_doi or secondary.is_enriched_by_doi

        # 9. Citation count (keep max)
        primary.citation_count = max(primary.citation_count, secondary.citation_count)

        return primary.finalize()

    @classmethod
    def deduplicate_list(
        cls,
        papers: List[CanonicalPaper],
        fuzzy_threshold: float = 0.92
    ) -> Tuple[List[CanonicalPaper], Dict[str, Any]]:
        """
        Executes 2-phase deduplication over an in-memory list of CanonicalPaper objects.
        """
        if not papers:
            return [], {
                "initial_count": 0,
                "final_count": 0,
                "duplicates_removed": 0,
                "exact_doi_matches": 0,
                "fuzzy_title_matches": 0,
            }

        initial_count = len(papers)
        exact_doi_matches = 0
        fuzzy_title_matches = 0

        # --- Phase 1: Exact Match by Normalized DOI ---
        doi_map: Dict[str, CanonicalPaper] = {}
        no_doi_papers: List[CanonicalPaper] = []

        for p in papers:
            p.finalize()
            if p.doi:
                norm_d = p.doi
                if norm_d in doi_map:
                    doi_map[norm_d] = cls.merge_papers(doi_map[norm_d], p)
                    exact_doi_matches += 1
                else:
                    doi_map[norm_d] = p
            else:
                no_doi_papers.append(p)

        phase1_papers = list(doi_map.values()) + no_doi_papers

        # --- Phase 2: Fuzzy Match on Title + Year + 1st Author ---
        deduped_final: List[CanonicalPaper] = []

        for candidate in phase1_papers:
            matched_index = None
            cand_title = candidate.normalized_title or normalize_title(candidate.title)
            cand_author = cls._extract_first_author_lastname(candidate.authors)

            for i, existing in enumerate(deduped_final):
                ex_title = existing.normalized_title or normalize_title(existing.title)

                # Rapid length check before expensive sequence matcher
                len_ratio = len(cand_title) / max(len(ex_title), 1)
                if len_ratio < 0.75 or len_ratio > 1.35:
                    continue

                # Year compatibility: either both match or at least one is unknown
                years_match = (
                    candidate.year is None
                    or existing.year is None
                    or candidate.year == existing.year
                )
                if not years_match:
                    continue

                # First author compatibility: if both present, must match
                ex_author = cls._extract_first_author_lastname(existing.authors)
                authors_match = (
                    not cand_author
                    or not ex_author
                    or cand_author == ex_author
                )
                if not authors_match:
                    continue

                # Title similarity ratio
                ratio = difflib.SequenceMatcher(None, cand_title, ex_title).ratio()
                if ratio >= fuzzy_threshold:
                    matched_index = i
                    break

            if matched_index is not None:
                deduped_final[matched_index] = cls.merge_papers(deduped_final[matched_index], candidate)
                fuzzy_title_matches += 1
            else:
                deduped_final.append(candidate)

        final_count = len(deduped_final)
        duplicates_removed = initial_count - final_count

        metrics = {
            "initial_count": initial_count,
            "final_count": final_count,
            "duplicates_removed": duplicates_removed,
            "exact_doi_matches": exact_doi_matches,
            "fuzzy_title_matches": fuzzy_title_matches,
        }

        return deduped_final, metrics

    @classmethod
    def deduplicate_database_corpus(
        cls,
        project_id: str = "default_slr",
        fuzzy_threshold: float = 0.92
    ) -> Dict[str, Any]:
        """
        Reads all corpus papers for a project from SQLite, executes 2-phase deduplication,
        and atomically updates the database.
        """
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT record_id, project_id, doi, normalized_title, title,
                   authors_json, year, venue, doc_type, abstract,
                   keywords_json, url, sources_json, raw_bibtex_key,
                   duplicate_count, is_enriched_by_doi, prisma_stage
            FROM corpus_papers
            WHERE project_id = ?
            """, (project_id,))
            rows = cursor.fetchall()

        if not rows:
            return {
                "project_id": project_id,
                "initial_count": 0,
                "final_count": 0,
                "duplicates_removed": 0,
                "exact_doi_matches": 0,
                "fuzzy_title_matches": 0,
            }

        papers = []
        for r in rows:
            p = CanonicalPaper(
                record_id=r["record_id"],
                doi=r["doi"],
                normalized_title=r["normalized_title"],
                title=r["title"],
                authors=json.loads(r["authors_json"] or "[]"),
                year=r["year"],
                venue=r["venue"],
                doc_type=r["doc_type"] or "other",
                abstract=r["abstract"] or "",
                keywords=json.loads(r["keywords_json"] or "[]"),
                url=r["url"] or "",
                sources=json.loads(r["sources_json"] or "[]"),
                raw_bibtex_key=r["raw_bibtex_key"] or "",
                duplicate_count=r["duplicate_count"] or 1,
                is_enriched_by_doi=bool(r["is_enriched_by_doi"]),
                prisma_stage=r["prisma_stage"] or "identification",
            )
            papers.append(p)

        deduped_papers, metrics = cls.deduplicate_list(papers, fuzzy_threshold=fuzzy_threshold)

        # Atomic replacement in database
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION;")
            try:
                # Remove old records for this project
                cursor.execute("DELETE FROM corpus_papers WHERE project_id = ?", (project_id,))

                # Insert deduplicated canonical set
                for p in deduped_papers:
                    p.finalize()
                    cursor.execute("""
                    INSERT INTO corpus_papers (
                        record_id, project_id, doi, normalized_title, title,
                        authors_json, year, venue, doc_type, abstract,
                        keywords_json, url, sources_json, raw_bibtex_key,
                        duplicate_count, is_enriched_by_doi, prisma_stage, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        p.record_id, project_id, p.doi, p.normalized_title, p.title,
                        json.dumps(p.authors), p.year, p.venue, p.doc_type, p.abstract,
                        json.dumps(p.keywords), p.url, json.dumps(p.sources), p.raw_bibtex_key,
                        p.duplicate_count, 1 if p.is_enriched_by_doi else 0, p.prisma_stage
                    ))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to persist deduplicated corpus: {e}")
                raise e

        metrics["project_id"] = project_id
        return metrics
