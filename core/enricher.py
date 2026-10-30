"""
Metadata Enricher for MCPCONECCT.
Silently completes missing abstracts and keywords using OpenAlex batching and Crossref fallback.
"""
from typing import Dict, Any, List, Optional
import html
import logging
import re
import httpx

from platforms.base import CanonicalPaper, normalize_doi
from core.db import get_connection

logger = logging.getLogger("mcpconecct.enricher")


class MetadataEnricher:
    """Enriches academic paper metadata via OpenAlex and Crossref APIs."""

    OPENALEX_WORKS_URL = "https://api.openalex.org/works"
    CROSSREF_WORKS_URL = "https://api.crossref.org/works"

    @staticmethod
    def reconstruct_inverted_index(inverted_index: Optional[Dict[str, List[int]]]) -> str:
        """
        Reconstructs continuous text from OpenAlex's abstract_inverted_index.
        Format: {"word": [pos1, pos2], "other": [pos0]} -> "other word ..."
        """
        if not inverted_index or not isinstance(inverted_index, dict):
            return ""

        pos_to_word = {}
        for word, positions in inverted_index.items():
            for p in positions:
                pos_to_word[p] = word

        if not pos_to_word:
            return ""

        sorted_words = [pos_to_word[i] for i in range(max(pos_to_word.keys()) + 1) if i in pos_to_word]
        return " ".join(sorted_words).strip()

    @classmethod
    def enrich_via_openalex(
        cls,
        papers_with_doi: List[CanonicalPaper],
        timeout: float = 10.0
    ) -> Dict[str, Dict[str, Any]]:
        """
        Queries OpenAlex batch endpoint for a list of papers (up to 50 DOIs).
        Returns a mapping of normalized DOI -> {"abstract": str, "keywords": List[str]}.
        """
        if not papers_with_doi:
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        # Prepare DOIs for filter: openalex accepts pipe-separated list
        # e.g. filter=doi:10.1145/123|10.1109/456
        dois = [p.doi for p in papers_with_doi if p.doi]
        if not dois:
            return {}

        filter_val = "|".join(dois[:50])
        headers = {
            "User-Agent": "MCPCONECCT/2.0 (mailto:academic-research@upeu.edu.pe)"
        }
        params = {
            "filter": f"doi:{filter_val}",
            "per-page": "50",
            "select": "doi,abstract_inverted_index,keywords",
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(cls.OPENALEX_WORKS_URL, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("results", []):
                        raw_doi = item.get("doi", "")
                        norm_d = normalize_doi(raw_doi)
                        if not norm_d:
                            continue

                        inv_index = item.get("abstract_inverted_index")
                        abstract_text = cls.reconstruct_inverted_index(inv_index)

                        raw_keywords = item.get("keywords", [])
                        extracted_keywords = []
                        for kw in raw_keywords:
                            if isinstance(kw, dict):
                                k_str = kw.get("keyword") or kw.get("display_name")
                                if k_str:
                                    extracted_keywords.append(k_str)
                            elif isinstance(kw, str):
                                extracted_keywords.append(kw)

                        results[norm_d] = {
                            "abstract": abstract_text,
                            "keywords": extracted_keywords,
                        }
        except Exception as e:
            logger.warning(f"OpenAlex batch enrichment request failed: {e}")

        return results

    @classmethod
    def enrich_single_crossref(cls, doi: str, timeout: float = 6.0) -> Dict[str, Any]:
        """
        Fallback enrichment for a single DOI querying Crossref REST API.
        """
        norm_doi = normalize_doi(doi)
        if not norm_doi:
            return {}

        headers = {
            "User-Agent": "MCPCONECCT/2.0 (mailto:academic-research@upeu.edu.pe)"
        }
        url = f"{cls.CROSSREF_WORKS_URL}/{norm_doi}"

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    item = resp.json().get("message", {})
                    raw_abstract = item.get("abstract", "")
                    clean_abstract = ""
                    if raw_abstract:
                        # Clean JATS XML tags (<jats:p>, <jats:title>, etc.)
                        no_tags = re.sub(r"<[^>]+>", " ", raw_abstract)
                        clean_abstract = " ".join(html.unescape(no_tags).split())

                    return {
                        "abstract": clean_abstract,
                        "keywords": item.get("subject", []),
                    }
        except Exception as e:
            logger.debug(f"Crossref fallback failed for DOI {norm_doi}: {e}")

        return {}

    @classmethod
    def enrich_papers(
        cls,
        papers: List[CanonicalPaper],
        batch_size: int = 50
    ) -> List[CanonicalPaper]:
        """
        Enriches a list of CanonicalPaper objects in batches.
        Only enriches papers with a valid DOI and missing or brief abstract (<40 chars).
        """
        candidates = [
            p for p in papers
            if p.doi and (not p.abstract or len(p.abstract.strip()) < 40)
        ]

        if not candidates:
            return papers

        # Process in batches of 50
        for i in range(0, len(candidates), batch_size):
            chunk = candidates[i:i + batch_size]
            openalex_data = cls.enrich_via_openalex(chunk)

            for paper in chunk:
                norm_d = paper.doi
                info = openalex_data.get(norm_d)
                enriched = False

                if info and info.get("abstract"):
                    paper.abstract = info["abstract"]
                    if info.get("keywords") and not paper.keywords:
                        paper.keywords = info["keywords"]
                    paper.is_enriched_by_doi = True
                    enriched = True

                # Fallback to Crossref if still missing
                if not enriched and (not paper.abstract or len(paper.abstract.strip()) < 40):
                    cr_info = cls.enrich_single_crossref(norm_d)
                    if cr_info.get("abstract"):
                        paper.abstract = cr_info["abstract"]
                        if cr_info.get("keywords") and not paper.keywords:
                            paper.keywords = cr_info["keywords"]
                        paper.is_enriched_by_doi = True

        return papers

    @classmethod
    def enrich_corpus_in_db(
        cls,
        project_id: str = "default_slr",
        batch_limit: int = 50
    ) -> Dict[str, Any]:
        """
        Enriches unenriched papers stored in SQLite corpus_papers table.
        """
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT record_id, doi, title, abstract, keywords_json, sources_json
            FROM corpus_papers
            WHERE project_id = ?
              AND doi IS NOT NULL
              AND doi != ''
              AND (abstract = '' OR length(abstract) < 40)
            LIMIT ?
            """, (project_id, batch_limit))
            rows = cursor.fetchall()

        if not rows:
            return {"project_id": project_id, "candidates_found": 0, "enriched_count": 0}

        papers_to_enrich = []
        for r in rows:
            p = CanonicalPaper(
                record_id=r["record_id"],
                doi=r["doi"],
                title=r["title"],
                abstract=r["abstract"] or "",
            )
            papers_to_enrich.append(p)

        enriched_list = cls.enrich_papers(papers_to_enrich)
        successful_count = 0

        with get_connection() as conn:
            cursor = conn.cursor()
            for p in enriched_list:
                if p.is_enriched_by_doi and p.abstract:
                    cursor.execute("""
                    UPDATE corpus_papers
                    SET abstract = ?,
                        is_enriched_by_doi = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE record_id = ?
                    """, (p.abstract, p.record_id))
                    successful_count += 1
            conn.commit()

        return {
            "project_id": project_id,
            "candidates_found": len(rows),
            "enriched_count": successful_count,
        }
