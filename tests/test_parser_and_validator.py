"""
Unit tests for QueryParser and QueryValidator.
Verifies platform-specific constraints including IEEE 10-wildcard limit and Scopus hyphen rule.
"""
import pytest
from core.query_parser import QueryParser
from core.query_validator import QueryValidator


def test_parentheses_and_quotes_balance():
    # Balanced
    errors = QueryParser.check_parentheses_and_quotes('(("All Metadata":"unlearnable*") OR ("All Metadata":"clean"))')
    assert len(errors) == 0

    # Unclosed parenthesis
    errors = QueryParser.check_parentheses_and_quotes('(("All Metadata":"unlearnable*") OR ("All Metadata":"clean")')
    assert len(errors) == 1
    assert "Unclosed opening parenthesis" in errors[0]

    # Unbalanced quotes
    errors = QueryParser.check_parentheses_and_quotes('("All Metadata":"unlearnable*)')
    assert any("Unbalanced double quotes" in e for e in errors)


def test_ieee_wildcard_limit_under_10():
    # Exactly 9 wildcards (the exact query from the user's SLR ESM_1.tex)
    query_9_wildcards = (
        '(("All Metadata":"unlearnable*") OR ("All Metadata":"defens*") OR '
        '("All Metadata":"attack*") OR ("All Metadata":"augment*") OR '
        '("All Metadata":"purif*") OR ("All Metadata":"accurac*") OR '
        '("All Metadata":"effective*") OR ("All Metadata":"generaliz*") OR '
        '("All Metadata":"imperceptib*"))'
    )
    report = QueryValidator.validate("ieee", query_9_wildcards)
    assert report.is_valid is True
    assert report.wildcard_count == 9
    assert len(report.errors) == 0


def test_ieee_wildcard_limit_exceeded():
    # 11 wildcards -> Must fail
    query_11_wildcards = (
        '("term1*" OR "term2*" OR "term3*" OR "term4*" OR "term5*" OR '
        '"term6*" OR "term7*" OR "term8*" OR "term9*" OR "term10*" OR "term11*")'
    )
    report = QueryValidator.validate("ieee", query_11_wildcards)
    assert report.is_valid is False
    assert report.wildcard_count == 11
    assert any("strictly limits queries to a maximum of 10 wildcards" in e for e in report.errors)


def test_scopus_hyphen_wildcard_warning():
    # "pre-train*" should trigger warning
    query_with_hyphen = 'TITLE-ABS-KEY ( "unlearnable*" AND "pre-train*" )'
    report = QueryValidator.validate("scopus", query_with_hyphen)
    assert any("Scopus does NOT expand wildcards following a hyphen" in w for w in report.warnings)

    # Explicit forms without wildcard after hyphen should not trigger hyphen warning
    query_clean = 'TITLE-ABS-KEY ( "unlearnable*" AND ( "pre-trained" OR "pre-training" ) )'
    report_clean = QueryValidator.validate("scopus", query_clean)
    assert not any("Scopus does NOT expand wildcards following a hyphen" in w for w in report_clean.warnings)


def test_springer_wildcard_warning():
    query = '("unlearnable*" OR "defens*")'
    report = QueryValidator.validate("springer", query)
    assert any("does not reliably expand wildcards" in w for w in report.warnings)
