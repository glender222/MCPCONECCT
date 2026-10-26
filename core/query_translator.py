"""
Query Translator for academic search equations.
Translates a canonical or PICO boolean search equation into native formats for:
- Scopus (TITLE-ABS-KEY, explicit hyphen expansions)
- IEEE Xplore (Command Search All Metadata, max 10 wildcard safety)
- Web of Science (TS= topic search)
- SpringerLink (explicit term conjunction)
"""
from typing import Dict, Any, List
import re

from core.query_parser import QueryParser


class QueryTranslator:
    """Translates canonical boolean queries into platform-specific syntaxes."""

    # Common English academic inflections for wildcard expansion when limiting wildcards
    EXPANSION_DICTIONARY = {
        "pre-train*": ['"pre-trained"', '"pre-training"'],
        "fine-tun*": ['"fine-tuning"', '"fine-tuned"'],
        "unlearnable*": ['"unlearnable"', '"unlearnability"'],
        "defens*": ['"defense"', '"defenses"', '"defensive"'],
        "defenc*": ['"defence"', '"defences"'],
        "attack*": ['"attack"', '"attacks"'],
        "augment*": ['"augmentation"', '"augmented"'],
        "purif*": ['"purification"', '"purified"'],
        "countermeasure*": ['"countermeasure"', '"countermeasures"'],
        "break*": ['"break"', '"breaking"'],
        "bypass*": ['"bypass"', '"bypassing"'],
        "circumvent*": ['"circumvent"', '"circumventing"'],
        "compress*": ['"compression"', '"compressed"'],
        "ensemble*": ['"ensemble"', '"ensembles"'],
        "distill*": ['"distillation"', '"distilled"'],
        "mix*": ['"mixed"', '"mixup"'],
        "baseline*": ['"baseline"', '"baselines"'],
        "benchmark*": ['"benchmark"', '"benchmarks"'],
        "outperform*": ['"outperform"', '"outperforms"'],
        "accurac*": ['"accuracy"', '"accuracies"'],
        "effective*": ['"effective"', '"effectiveness"'],
        "imperceptib*": ['"imperceptible"', '"imperceptibility"'],
        "generaliz*": ['"generalization"', '"generalizable"'],
        "performance*": ['"performance"', '"performances"'],
        "perturbation*": ['"perturbation"', '"perturbations"'],
        "poison*": ['"poisoning"', '"poisons"'],
        "image*": ['"image"', '"images"'],
        "rate*": ['"rate"', '"rates"'],
    }

    @classmethod
    def translate_all(cls, query: str) -> Dict[str, str]:
        """Translates canonical query into all 4 supported databases."""
        return {
            "scopus": cls.to_scopus(query),
            "ieee": cls.to_ieee(query),
            "wos": cls.to_wos(query),
            "springer": cls.to_springer(query),
        }

    @classmethod
    def to_scopus(cls, query: str) -> str:
        """Translates to Scopus TITLE-ABS-KEY syntax with hyphen-wildcard handling."""
        clauses = QueryParser.extract_clauses(query)
        scopus_blocks = []

        for clause in clauses:
            clean_clause = clause.strip()
            # Remove existing wrapper if present
            if clean_clause.startswith("(") and clean_clause.endswith(")"):
                inner = clean_clause[1:-1].strip()
            else:
                inner = clean_clause

            # Expand hyphenated wildcards
            for term, expansions in cls.EXPANSION_DICTIONARY.items():
                if "-" in term and term in inner:
                    inner = inner.replace(term, " OR ".join(expansions))

            # Ensure uppercase boolean operators
            inner = re.sub(r'\band\b', 'AND', inner, flags=re.IGNORECASE)
            inner = re.sub(r'\bor\b', 'OR', inner, flags=re.IGNORECASE)
            inner = re.sub(r'\bnot\b', 'AND NOT', inner, flags=re.IGNORECASE)

            scopus_blocks.append(f"TITLE-ABS-KEY ( {inner} )")

        return " AND ".join(scopus_blocks)

    @classmethod
    def to_wos(cls, query: str) -> str:
        """Translates to Web of Science TS=(...) syntax."""
        clauses = QueryParser.extract_clauses(query)
        wos_blocks = []

        for clause in clauses:
            clean_clause = clause.strip()
            if clean_clause.startswith("(") and clean_clause.endswith(")"):
                inner = clean_clause[1:-1].strip()
            else:
                inner = clean_clause

            # Standardize boolean operators
            inner = re.sub(r'\band\b', 'AND', inner, flags=re.IGNORECASE)
            inner = re.sub(r'\bor\b', 'OR', inner, flags=re.IGNORECASE)
            inner = re.sub(r'\bnot\b', 'NOT', inner, flags=re.IGNORECASE)

            wos_blocks.append(f"TS=({inner})")

        return " AND ".join(wos_blocks)

    @classmethod
    def to_ieee(cls, query: str) -> str:
        """
        Translates to IEEE Xplore Command Search syntax.
        Converts terms to (("All Metadata":"<term>") OR ...)
        and enforces the 10-wildcard limit by expanding excess wildcards.
        """
        clauses = QueryParser.extract_clauses(query)
        ieee_blocks = []

        wildcard_budget = 10  # Max permitted by IEEE Command Search

        for clause in clauses:
            clean_clause = clause.strip()
            if clean_clause.startswith("(") and clean_clause.endswith(")"):
                inner = clean_clause[1:-1].strip()
            else:
                inner = clean_clause

            # Split on OR while respecting quotes
            terms = re.split(r'\s+OR\s+', inner, flags=re.IGNORECASE)
            clause_parts = []

            for raw_term in terms:
                term = raw_term.strip().strip('"').strip("'")
                if not term:
                    continue

                if "*" in term:
                    if wildcard_budget > 0:
                        clause_parts.append(f'("All Metadata":"{term}")')
                        wildcard_budget -= term.count("*")
                    else:
                        # Budget exceeded: Expand to explicit forms if available, else strip *
                        if f"{term}" in cls.EXPANSION_DICTIONARY:
                            for exp in cls.EXPANSION_DICTIONARY[term]:
                                clause_parts.append(f'("All Metadata":{exp})')
                        elif f'"{term}"' in cls.EXPANSION_DICTIONARY:
                            for exp in cls.EXPANSION_DICTIONARY[f'"{term}"']:
                                clause_parts.append(f'("All Metadata":{exp})')
                        else:
                            clean_stem = term.replace("*", "")
                            clause_parts.append(f'("All Metadata":"{clean_stem}")')
                else:
                    clause_parts.append(f'("All Metadata":"{term}")')

            if clause_parts:
                ieee_blocks.append("(" + " OR ".join(clause_parts) + ")")

        return " AND ".join(ieee_blocks)

    @classmethod
    def to_springer(cls, query: str) -> str:
        """Translates to SpringerLink search syntax (explicit terms without wildcards)."""
        clauses = QueryParser.extract_clauses(query)
        springer_blocks = []

        for clause in clauses:
            clean_clause = clause.strip()
            if clean_clause.startswith("(") and clean_clause.endswith(")"):
                inner = clean_clause[1:-1].strip()
            else:
                inner = clean_clause

            terms = re.split(r'\s+OR\s+', inner, flags=re.IGNORECASE)
            springer_terms = []

            for raw_term in terms:
                term = raw_term.strip().strip('"').strip("'")
                if not term:
                    continue

                if "*" in term:
                    # Replace with expansions or stem
                    if term in cls.EXPANSION_DICTIONARY:
                        springer_terms.extend(cls.EXPANSION_DICTIONARY[term])
                    elif f'"{term}"' in cls.EXPANSION_DICTIONARY:
                        springer_terms.extend(cls.EXPANSION_DICTIONARY[f'"{term}"'])
                    else:
                        clean_stem = term.replace("*", "")
                        springer_terms.append(f'"{clean_stem}"')
                else:
                    springer_terms.append(f'"{term}"')

            if springer_terms:
                springer_blocks.append("(" + " OR ".join(springer_terms) + ")")

        return " AND ".join(springer_blocks)
