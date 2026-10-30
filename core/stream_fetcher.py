"""
Bulk Stream Fetcher for MCPCONECCT.
Handles automated multi-page downloading, caching, random jitter (0.75-1.65s),
exponential backoff, WAF detection, silent DOI enrichment, and corpus persistence.
"""
from typing import Dict, Any, List, Optional
import time
import random
import uuid
import logging

from config import settings
from platforms import get_platform
from platforms.base import CanonicalPaper
from core.db import (
    create_ingestion_job,
    update_job_progress,
    upsert_corpus_paper,
    get_connection,
)
from core.cache import QueryCacheManager
from core.enricher import MetadataEnricher
from core.deduplicator import CorpusDeduplicator

logger = logging.getLogger("mcpconecct.stream_fetcher")


class BulkStreamFetcher:
    """Manages resilient multi-page streaming downloads with anti-bot pacing."""

    def __init__(
        self,
        database: str,
        query: str,
        max_records: int = 100,
        page_size: int = 25,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        doc_types: Optional[List[str]] = None,
        project_id: str = "default_slr",
        enrich_missing_abstracts: bool = True,
    ):
        self.database = database.lower().strip()
        self.query = query.strip()
        self.max_records = max(1, max_records)
        self.page_size = min(max(5, page_size), 50)
        self.year_start = year_start
        self.year_end = year_end
        self.doc_types = doc_types or []
        self.project_id = project_id
        self.enrich_missing_abstracts = enrich_missing_abstracts
        self.job_id = f"job_{uuid.uuid4().hex[:12]}"

    def execute(self) -> Dict[str, Any]:
        """
        Executes the full streaming ingestion workflow synchronously or within background task.
        """
        create_ingestion_job(
            job_id=self.job_id,
            database_name=self.database,
            query=self.query,
            total_expected=self.max_records,
            project_id=self.project_id,
        )

        try:
            adapter = get_platform(self.database)
        except Exception as e:
            update_job_progress(self.job_id, status="FAILED", error_message=str(e))
            return {"job_id": self.job_id, "status": "FAILED", "error": str(e)}

        total_fetched = 0
        total_enriched = 0
        current_page = 1
        known_total_available = None

        while total_fetched < self.max_records:
            current_batch_size = min(self.page_size, self.max_records - total_fetched)
            query_hash = QueryCacheManager.compute_hash(
                database=self.database,
                query=self.query,
                year_start=self.year_start,
                year_end=self.year_end,
                doc_types=self.doc_types,
                page=current_page,
                page_size=current_batch_size,
            )

            cached_data = QueryCacheManager.get_cached_page(query_hash, ttl_hours=48)
            search_data = None

            if cached_data:
                logger.info(f"[{self.database}] Page {current_page} loaded from 48h cache.")
                search_data = cached_data
            else:
                # Network fetch with exponential backoff and jitter
                backoff_delays = [2.0, 4.0, 8.0]
                fetch_success = False

                for attempt, delay in enumerate(backoff_delays, start=1):
                    try:
                        search_data = adapter.search(
                            query=self.query,
                            year_start=self.year_start,
                            year_end=self.year_end,
                            doc_types=self.doc_types,
                            page=current_page,
                            page_size=current_batch_size,
                        )
                        fetch_success = True
                        break
                    except Exception as exc:
                        exc_str = str(exc).lower()
                        # Detect WAF / Cloudflare
                        if any(w in exc_str for w in ["cloudflare", "waf", "challenge", "turnstile", "captcha", "access denied"]):
                            logger.error(f"WAF Challenge detected on page {current_page}: {exc}")
                            update_job_progress(
                                self.job_id,
                                status="PAUSED_WAF",
                                error_message=f"Paused due to WAF challenge on {self.database}. Total items preserved: {total_fetched}",
                            )
                            return {
                                "job_id": self.job_id,
                                "status": "PAUSED_WAF",
                                "fetched_count": total_fetched,
                                "message": f"WAF challenge detected on {self.database}. Download paused safely.",
                            }

                        logger.warning(f"Fetch attempt {attempt} failed ({exc}). Retrying in {delay}s...")
                        time.sleep(delay)

                if not fetch_success or not search_data:
                    err_msg = f"Failed to retrieve page {current_page} after {len(backoff_delays)} retries."
                    update_job_progress(self.job_id, status="FAILED", error_message=err_msg)
                    return {"job_id": self.job_id, "status": "FAILED", "error": err_msg}

                # Cache newly fetched page
                QueryCacheManager.set_cached_page(
                    query_hash=query_hash,
                    database=self.database,
                    query=self.query,
                    response_data=search_data,
                    year_start=self.year_start,
                    year_end=self.year_end,
                    doc_types=self.doc_types,
                    page=current_page,
                    page_size=current_batch_size,
                    total_hits=search_data.get("total_results", 0),
                )

                # Random Jitter between network pages (0.75 - 1.65 seconds)
                time.sleep(random.uniform(0.75, 1.65))

            raw_papers = search_data.get("papers", [])
            if not raw_papers:
                break

            if known_total_available is None:
                known_total_available = search_data.get("total_results", 0)

            # Convert to CanonicalPaper models
            canonical_papers: List[CanonicalPaper] = []
            for p_dict in raw_papers:
                p_obj = CanonicalPaper(
                    title=p_dict.get("title", ""),
                    authors=p_dict.get("authors", []),
                    year=p_dict.get("year"),
                    doi=p_dict.get("doi"),
                    venue=p_dict.get("venue"),
                    doc_type=p_dict.get("doc_type", "other"),
                    abstract=p_dict.get("abstract", "") or "",
                    keywords=p_dict.get("keywords", []),
                    url=p_dict.get("url", ""),
                    sources=p_dict.get("sources", [self.database]),
                    raw_bibtex_key=p_dict.get("raw_bibtex_key", ""),
                    citation_count=p_dict.get("citation_count", 0),
                ).finalize()
                canonical_papers.append(p_obj)

            # Silent Metadata Enrichment via DOI (OpenAlex / Crossref)
            if self.enrich_missing_abstracts:
                canonical_papers = MetadataEnricher.enrich_papers(canonical_papers)
                enriched_in_page = sum(1 for p in canonical_papers if p.is_enriched_by_doi)
                total_enriched += enriched_in_page

            # Upsert into corpus_papers table
            for p in canonical_papers:
                upsert_corpus_paper({
                    "record_id": p.record_id,
                    "project_id": self.project_id,
                    "doi": p.doi,
                    "normalized_title": p.normalized_title,
                    "title": p.title,
                    "authors": p.authors,
                    "year": p.year,
                    "venue": p.venue,
                    "doc_type": p.doc_type,
                    "abstract": p.abstract,
                    "keywords": p.keywords,
                    "url": p.url,
                    "sources": p.sources,
                    "raw_bibtex_key": p.raw_bibtex_key,
                    "duplicate_count": p.duplicate_count,
                    "is_enriched_by_doi": p.is_enriched_by_doi,
                })

            total_fetched += len(canonical_papers)
            update_job_progress(
                self.job_id,
                fetched_count=total_fetched,
                enriched_count=total_enriched,
            )

            # Check if all available records in the platform were exhausted
            if len(raw_papers) < current_batch_size:
                break

            current_page += 1

        # Post-ingestion cross-database deduplication pass
        dedup_metrics = CorpusDeduplicator.deduplicate_database_corpus(self.project_id)
        final_dedup_count = dedup_metrics.get("final_count", total_fetched)

        update_job_progress(
            self.job_id,
            status="COMPLETED",
            deduplicated_count=final_dedup_count,
        )

        return {
            "job_id": self.job_id,
            "status": "COMPLETED",
            "project_id": self.project_id,
            "database": self.database,
            "total_fetched": total_fetched,
            "total_enriched": total_enriched,
            "deduplicated_count": final_dedup_count,
            "duplicates_removed": dedup_metrics.get("duplicates_removed", 0),
        }
