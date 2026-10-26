"""
Validation and translation MCP tools.
"""
from typing import Dict, Any, List, Optional
from core.query_validator import QueryValidator
from core.query_translator import QueryTranslator


def validate_search_string(database: str, query: str) -> Dict[str, Any]:
    """
    Validates the syntax and database-specific constraints of a boolean search equation.
    Checks parentheses balance, quotes, field tags, and strict platform rules:
    - Scopus: warns against hyphenated wildcards (e.g. 'pre-train*').
    - IEEE Xplore: strictly enforces the maximum limit of 10 wildcards (*).
    - Web of Science: checks TS=(...) topic tagging.
    - SpringerLink: warns of wildcard incompatibility in basic search and lax conjunctions.

    Args:
        database: Target platform ('scopus', 'ieee', 'wos', 'springer').
        query: The boolean search equation string.
    """
    report = QueryValidator.validate(database, query)
    return report.model_dump()


def translate_search_string(
    query: str,
    target_databases: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Translates a canonical boolean equation into native syntax for academic databases:
    - Scopus: TITLE-ABS-KEY blocks with explicit hyphen-wildcard expansion.
    - IEEE Xplore: Command Search format (("All Metadata":"...") OR ...) respecting the 10 wildcard ceiling.
    - Web of Science: TS=(...) topic clauses.
    - SpringerLink: explicit term clauses without unsupported wildcards.

    Args:
        query: Canonical boolean query string.
        target_databases: Optional list of databases. Defaults to all 4 ['scopus', 'ieee', 'wos', 'springer'].
    """
    translations = QueryTranslator.translate_all(query)
    if target_databases:
        return {db.lower(): translations.get(db.lower(), "") for db in target_databases}
    return translations


def register_validation_tools(mcp) -> None:
    mcp.tool()(validate_search_string)
    mcp.tool()(translate_search_string)
