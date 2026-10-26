"""
Query Validator for academic databases (Scopus, IEEE Xplore, WoS, SpringerLink).
Enforces database-specific syntax rules, field tagging, wildcard limitations,
and operator standards.
"""
from typing import Dict, Any, List
from pydantic import BaseModel, Field

from core.query_parser import QueryParser


class ValidationReport(BaseModel):
    database: str
    is_valid: bool
    wildcard_count: int
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class QueryValidator:
    """Validates boolean equations against specific academic platform constraints."""

    @classmethod
    def validate(cls, database: str, query: str) -> ValidationReport:
        db = database.lower().strip()
        query = query.strip()

        if not query:
            return ValidationReport(
                database=db,
                is_valid=False,
                wildcard_count=0,
                errors=["Query is empty."],
                warnings=[],
                suggestions=["Provide a non-empty boolean search query."],
            )

        # 1. Universal syntax checks (quotes and parentheses)
        syntax_errors = QueryParser.check_parentheses_and_quotes(query)
        wildcards = QueryParser.find_wildcards(query)
        total_wildcards = QueryParser.count_total_wildcards(query)

        errors = list(syntax_errors)
        warnings = []
        suggestions = []

        # 2. Database-specific validation
        if db == "scopus":
            cls._validate_scopus(query, total_wildcards, errors, warnings, suggestions)
        elif db == "ieee":
            cls._validate_ieee(query, total_wildcards, errors, warnings, suggestions)
        elif db == "wos":
            cls._validate_wos(query, total_wildcards, errors, warnings, suggestions)
        elif db == "springer":
            cls._validate_springer(query, total_wildcards, errors, warnings, suggestions)
        else:
            warnings.append(f"Database '{database}' is not one of the standard platforms (scopus, ieee, wos, springer). Running standard boolean validation.")

        is_valid = len(errors) == 0

        return ValidationReport(
            database=db,
            is_valid=is_valid,
            wildcard_count=total_wildcards,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    @classmethod
    def _validate_scopus(
        cls, query: str, wildcard_count: int,
        errors: List[str], warnings: List[str], suggestions: List[str]
    ) -> None:
        # Check field tags
        if "TITLE-ABS-KEY" not in query and "TITLE(" not in query:
            warnings.append(
                "Query does not explicitly use 'TITLE-ABS-KEY (...)'. "
                "In Scopus Advanced Search, enclosing terms in 'TITLE-ABS-KEY ( ... )' is standard for SLR protocols."
            )
            suggestions.append("Wrap search blocks in 'TITLE-ABS-KEY ( ... )'.")

        # Check hyphenated wildcards
        hyphen_issues = QueryParser.find_hyphenated_wildcards(query)
        if hyphen_issues:
            warnings.append(
                f"Scopus does NOT expand wildcards following a hyphen. Found: {', '.join(hyphen_issues)}. "
                "These terms will fail to match intended variants in Scopus."
            )
            suggestions.append(
                "Replace hyphenated wildcards (e.g. 'pre-train*') with explicit variants (e.g. '\"pre-trained\" OR \"pre-training\"')."
            )

        # Check for NOT vs AND NOT
        if " NOT " in query and " AND NOT " not in query:
            warnings.append("Scopus requires 'AND NOT' instead of standalone 'NOT'.")
            suggestions.append("Replace 'NOT' with 'AND NOT'.")

    @classmethod
    def _validate_ieee(
        cls, query: str, wildcard_count: int,
        errors: List[str], warnings: List[str], suggestions: List[str]
    ) -> None:
        # Strict IEEE Xplore wildcard limitation: Maximum 10 wildcards
        if wildcard_count > 10:
            errors.append(
                f"IEEE Xplore Command Search strictly limits queries to a maximum of 10 wildcards (*). "
                f"Found {wildcard_count} wildcards."
            )
            suggestions.append(
                f"Reduce the number of wildcards from {wildcard_count} down to 10 or fewer. "
                "Expand the most common variations into explicit plural/inflection words."
            )
        else:
            warnings.append(f"IEEE Xplore wildcard usage: {wildcard_count}/10 used.")

        # Check Command Search field syntax
        if "All Metadata" not in query and "Document Title" not in query:
            warnings.append(
                "IEEE Command Search typically specifies field tags like '(\"All Metadata\":\"...\")'. "
                "Unscoped terms may search across full text leading to high noise."
            )
            suggestions.append("Format clauses as ((\"All Metadata\":\"term*\") OR ...).")

        # Check lowercase boolean operators
        for op in [" and ", " or ", " not "]:
            if op in query:
                warnings.append(f"Found lowercase boolean operator '{op.strip()}'. IEEE Xplore requires UPPERCASE 'AND', 'OR', 'NOT'.")
                suggestions.append("Ensure all boolean operators are capitalized (AND, OR, NOT).")

    @classmethod
    def _validate_wos(
        cls, query: str, wildcard_count: int,
        errors: List[str], warnings: List[str], suggestions: List[str]
    ) -> None:
        # Check field tag TS=
        if "TS=" not in query and "TI=" not in query:
            warnings.append(
                "Query does not specify a Web of Science field tag such as 'TS=' (Topic). "
                "For Advanced Search, 'TS=(...)' searches Title, Abstract, Author Keywords, and Keywords Plus."
            )
            suggestions.append("Prefix topic blocks with 'TS=(...)'.")

    @classmethod
    def _validate_springer(
        cls, query: str, wildcard_count: int,
        errors: List[str], warnings: List[str], suggestions: List[str]
    ) -> None:
        if wildcard_count > 0:
            warnings.append(
                f"SpringerLink basic search does not reliably expand wildcards (*). Found {wildcard_count} wildcards. "
                "Explicit full-word terms should be used."
            )
            suggestions.append("Expand wildcards into exact terms without asterisks for SpringerLink.")

        warnings.append(
            "SpringerLink evaluates boolean conjunctions (AND) laxly, which may introduce noise into results compared to Scopus/WoS."
        )
