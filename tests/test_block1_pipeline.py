"""
Comprehensive Unit and Integration Test Suite for MCPCONECCT v2.0 (Block 1).
Covers Canonical Data Contract, OpenAlex Reconstruction, 2-Phase Deduplication,
Query Cache Manager, RIS & Citation Formatter, SQLite WAL Concurrency, and REST API Endpoints.
"""
from typing import Dict, Any, List
import pytest
from fastapi.testclient import TestClient

from platforms.base import CanonicalPaper, normalize_doi, normalize_title, generate_bibtex_key
from core.enricher import MetadataEnricher
from core.deduplicator import CorpusDeduplicator
from core.cache import QueryCacheManager
from core.db import (
    init_db,
    upsert_corpus_paper,
    get_corpus_papers,
    get_corpus_summary,
    create_ingestion_job,
    update_job_progress,
    get_ingestion_job,
    get_connection,
)
from exporters.ris_exporter import RisExporter
from exporters.citation_formatter import CitationFormatter
from dashboard.app import app


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db()


# 1. Canonical Paper & Normalization Tests

def test_canonical_paper_normalization():
    # Test DOI cleaning
    assert normalize_doi("https://doi.org/10.1109/CVPR.2023.12345") == "10.1109/cvpr.2023.12345"
    assert normalize_doi("http://dx.doi.org/10.1007/s00521-022-07") == "10.1007/s00521-022-07"
    assert normalize_doi("doi: 10.1016/j.patrec.2021.05.001") == "10.1016/j.patrec.2021.05.001"
    assert normalize_doi("invalid_doi_without_prefix") is None
    assert normalize_doi(None) is None

    # Test title normalization
    dirty_title = "<b>Deep</b> Learning for <i>Medical</i> Imaging: A   Survey!"
    clean_title = normalize_title(dirty_title)
    assert clean_title == "deep learning for medical imaging a survey"

    # Test BibTeX key generation
    authors = ["Hanxun Huang", "Xingjun Ma"]
    key = generate_bibtex_key(authors, 2021, "Unlearnable Examples in Deep Networks")
    assert key == "huang2021unlearnable"

    # Test CanonicalPaper finalize and record_id
    paper = CanonicalPaper(
        title="Unlearnable Examples: Making Personal Data Unexploitable",
        authors=["Hanxun Huang", "Xingjun Ma"],
        year=2021,
        doi="https://doi.org/10.1109/ICCV48922.2021.00880",
        sources=["ieee"]
    ).finalize()

    assert paper.doi == "10.1109/iccv48922.2021.00880"
    assert paper.normalized_title == "unlearnable examples making personal data unexploitable"
    assert len(paper.record_id) == 24
    assert paper.raw_bibtex_key == "huang2021unlearnable"

    paper_dict = paper.to_dict()
    assert paper_dict["database"] == "ieee"
    assert paper_dict["year"] == 2021


# 2. OpenAlex Inverted Index Reconstruction

def test_openalex_inverted_index_reconstruction():
    inverted_index = {
        "This": [0],
        "systematic": [1],
        "review": [2],
        "synthesizes": [3],
        "proactive": [4],
        "poisoning": [5],
        "defenses": [6],
        "in": [7],
        "deep": [8],
        "learning.": [9],
    }
    reconstructed = MetadataEnricher.reconstruct_inverted_index(inverted_index)
    expected = "This systematic review synthesizes proactive poisoning defenses in deep learning."
    assert reconstructed == expected

    # Test empty or invalid index
    assert MetadataEnricher.reconstruct_inverted_index(None) == ""
    assert MetadataEnricher.reconstruct_inverted_index({}) == ""


# 3. Two-Phase Cross-Database Deduplicator Tests

def test_two_phase_deduplicator():
    # Phase 1: Exact Match by DOI
    p1 = CanonicalPaper(
        title="Availability Attacks Create Shortcuts",
        authors=["Chuan Guo", "Alexandre Sablayrolles"],
        year=2022,
        doi="10.1038/s41467-022-12345-6",
        abstract="Short abstract",
        sources=["scopus"],
        keywords=["AI", "Robustness"]
    ).finalize()

    p2 = CanonicalPaper(
        title="Availability Attacks Create Shortcuts in Deep Neural Networks",
        authors=["Chuan Guo", "A. Sablayrolles", "H. Jegou"],
        year=2022,
        doi="10.1038/s41467-022-12345-6",
        abstract="Much longer abstract explaining that availability attacks create shortcuts in neural networks.",
        sources=["ieee"],
        keywords=["Shortcuts", "Robustness"]
    ).finalize()

    merged_list, metrics = CorpusDeduplicator.deduplicate_list([p1, p2])
    assert len(merged_list) == 1
    assert metrics["exact_doi_matches"] == 1
    assert metrics["duplicates_removed"] == 1

    merged = merged_list[0]
    assert "scopus" in merged.sources and "ieee" in merged.sources
    assert merged.duplicate_count == 2
    assert len(merged.abstract) > 40
    assert len(merged.authors) == 3
    assert "Shortcuts" in merged.keywords and "AI" in merged.keywords

    # Phase 2: Fuzzy Match on Title (without DOI)
    p3 = CanonicalPaper(
        title="Adversarial Examples in Deep Learning",
        authors=["Goodfellow, Ian"],
        year=2015,
        doi=None,
        sources=["springer"]
    ).finalize()

    p4 = CanonicalPaper(
        title="Adversarial Examples in Deep Learning: An Overview",
        authors=["I. Goodfellow"],
        year=2015,
        doi=None,
        sources=["wos"]
    ).finalize()

    merged_fuzzy, m_fuzzy = CorpusDeduplicator.deduplicate_list([p3, p4], fuzzy_threshold=0.80)
    assert len(merged_fuzzy) == 1
    assert m_fuzzy["fuzzy_title_matches"] == 1
    assert "springer" in merged_fuzzy[0].sources and "wos" in merged_fuzzy[0].sources


# 4. Query Cache Manager Tests

def test_query_cache_manager():
    db = "ieee"
    query = "  adversarial   machine  learning  "
    h1 = QueryCacheManager.compute_hash(db, query, 2020, 2024, ["Article", "Conference Paper"])
    h2 = QueryCacheManager.compute_hash("ieee", "adversarial machine learning", 2020, 2024, ["Conference Paper", "Article"])

    # Deterministic hash regardless of whitespace or doc_type order
    assert h1 == h2

    # Set and get cache
    sample_response = {"total_results": 42, "papers": [{"title": "Cached Paper"}]}
    QueryCacheManager.set_cached_page(h1, db, query, sample_response, 2020, 2024, ["Article"], total_hits=42)

    cached = QueryCacheManager.get_cached_page(h1, ttl_hours=48)
    assert cached is not None
    assert cached["total_results"] == 42
    assert cached["papers"][0]["title"] == "Cached Paper"

    # Test cache expiration check
    expired = QueryCacheManager.get_cached_page(h1, ttl_hours=0)
    assert expired is None


# 5. RIS Exporter & Citation Formatter Tests

def test_ris_and_citation_formatter():
    paper = {
        "record_id": "test_rec_123",
        "title": "Making Personal Data Unexploitable with Unlearnable Examples",
        "authors": ["Hanxun Huang", "Xingjun Ma", "James Bailey"],
        "year": 2021,
        "doi": "10.1109/ICCV48922.2021.00880",
        "venue": "IEEE ICCV",
        "doc_type": "Conference Paper",
        "abstract": "We propose unlearnable examples to protect user privacy.",
        "keywords": ["Privacy", "Poisoning"],
        "sources": ["ieee", "scopus"],
    }

    # Test RIS Export
    ris_entry = RisExporter.format_entry(paper)
    assert "TY  - CONF" in ris_entry
    assert "TI  - Making Personal Data Unexploitable with Unlearnable Examples" in ris_entry
    assert "AU  - Hanxun Huang" in ris_entry
    assert "PY  - 2021" in ris_entry
    assert "DO  - 10.1109/ICCV48922.2021.00880" in ris_entry
    assert "DB  - ieee, scopus" in ris_entry
    assert "ER  -" in ris_entry

    # Test IEEE Citation
    ieee_cit = CitationFormatter.format_ieee(paper, index=1)
    assert ieee_cit.startswith("[1] H. Huang, X. Ma, and J. Bailey, \"Making Personal Data Unexploitable with Unlearnable Examples,\"")
    assert "doi: 10.1109/ICCV48922.2021.00880." in ieee_cit

    # Test APA 7 Citation
    apa_cit = CitationFormatter.format_apa7(paper)
    assert apa_cit.startswith("Huang, H., Ma, X., & Bailey, J. (2021).")
    assert "https://doi.org/10.1109/ICCV48922.2021.00880" in apa_cit

    # Test LaTeX Bibitem
    bibitem = CitationFormatter.format_bibitem(paper, index=1)
    assert "\\bibitem{" in bibitem
    assert "H. Huang, X. Ma, J. Bailey" in bibitem


# 6. SQLite WAL Concurrency & Ingestion Jobs Tracking

def test_db_concurrency_and_jobs():
    import uuid
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode.lower() == "wal"

    job_id = f"test_job_{uuid.uuid4().hex[:8]}"
    create_ingestion_job(
        job_id=job_id,
        database_name="springer",
        query="adversarial learning",
        total_expected=100,
        project_id="test_project",
    )

    update_job_progress(job_id, fetched_count=25, enriched_count=10, deduplicated_count=20, status="RUNNING")
    job = get_ingestion_job(job_id)
    assert job is not None
    assert job["fetched_count"] == 25
    assert job["enriched_count"] == 10
    assert job["status"] == "RUNNING"

    update_job_progress(job_id, fetched_count=100, status="COMPLETED")
    job_completed = get_ingestion_job(job_id)
    assert job_completed["status"] == "COMPLETED"
    assert job_completed["fetched_count"] == 100


# 7. FastAPI REST Endpoints for Block 1

def test_api_endpoints_block1():
    client = TestClient(app)

    # Test diagnostics endpoint
    resp_diag = client.get("/api/connections/diagnose")
    assert resp_diag.status_code == 200
    diag_data = resp_diag.json()
    assert "diagnostics" in diag_data
    assert "ieee" in diag_data["diagnostics"]
    assert "springer" in diag_data["diagnostics"]

    # Test corpus papers listing
    resp_papers = client.get("/api/corpus/papers?project_id=default_slr")
    assert resp_papers.status_code == 200
    papers_data = resp_papers.json()
    assert "summary" in papers_data
    assert "papers" in papers_data

    # Test corpus deduplicate endpoint
    resp_dedup = client.post("/api/corpus/deduplicate", json={"project_id": "default_slr", "fuzzy_threshold": 0.92})
    assert resp_dedup.status_code == 200
    dedup_res = resp_dedup.json()
    assert "duplicates_removed" in dedup_res
    assert "final_count" in dedup_res
