"""
Query parser and AST/token analysis for academic boolean search equations.
Handles parentheses balancing, quote matching, wildcard detection, and tokenization.
"""
from typing import List, Dict, Any, Tuple
import re


class QueryParser:
    """Parses and inspects academic boolean queries."""

    OPERATORS = {"AND", "OR", "NOT", "AND NOT", "NEAR", "SAME"}

    @classmethod
    def check_parentheses_and_quotes(cls, query: str) -> List[str]:
        """Checks for balanced parentheses and closed quotation marks."""
        errors = []

        # Check quotes
        quote_count = query.count('"')
        if quote_count % 2 != 0:
            errors.append(f"Unbalanced double quotes: found {quote_count} quotes (must be an even number).")

        # Check parentheses
        stack = []
        for idx, char in enumerate(query):
            if char == "(":
                stack.append(idx)
            elif char == ")":
                if not stack:
                    errors.append(f"Unmatched closing parenthesis ')' at character position {idx}.")
                else:
                    stack.pop()

        if stack:
            errors.append(f"Unclosed opening parenthesis '(': {len(stack)} unclosed parentheses.")

        return errors

    @classmethod
    def find_wildcards(cls, query: str) -> List[Dict[str, Any]]:
        """
        Finds all occurrences of wildcards (*) and extracts the enclosing token/phrase.
        """
        wildcards = []
        # Match words with asterisks, including inside quotes
        pattern = re.compile(r'([a-zA-Z0-9_\-\"\'*]+[*][a-zA-Z0-9_\-\"\'*]*)')
        for match in pattern.finditer(query):
            token = match.group(1)
            # count how many asterisks in this token
            num_stars = token.count("*")
            wildcards.append({
                "token": token,
                "start": match.start(),
                "end": match.end(),
                "asterisk_count": num_stars,
            })
        return wildcards

    @classmethod
    def find_hyphenated_wildcards(cls, query: str) -> List[str]:
        """
        Detects terms where a wildcard appears after a hyphen (e.g. 'pre-train*').
        Scopus treats the hyphen as a term separator and will fail to match/expand these.
        """
        issues = []
        pattern = re.compile(r'["\']?[a-zA-Z0-9]+-[a-zA-Z0-9]*\*["\']?')
        for match in pattern.finditer(query):
            issues.append(match.group(0))
        return issues

    @classmethod
    def count_total_wildcards(cls, query: str) -> int:
        """Returns total count of '*' characters in the query."""
        return query.count("*")

    @classmethod
    def extract_clauses(cls, query: str) -> List[str]:
        """
        Splits high-level AND blocks while preserving nested parentheses.
        """
        clauses = []
        depth = 0
        current = []
        i = 0
        n = len(query)

        while i < n:
            # Check for high-level AND
            if depth == 0 and query[i:i+5].upper() == " AND ":
                clause = "".join(current).strip()
                if clause:
                    clauses.append(clause)
                current = []
                i += 5
                continue

            char = query[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)

            current.append(char)
            i += 1

        final_clause = "".join(current).strip()
        if final_clause:
            clauses.append(final_clause)

        return clauses
