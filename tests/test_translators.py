"""
Unit tests for QueryTranslator.
Verifies cross-platform translation across Scopus, IEEE, WoS, and SpringerLink.
"""
from core.query_translator import QueryTranslator


def test_translate_to_scopus():
    query = '("unlearnable*" OR "pre-train*") AND ("defens*" OR "clean")'
    scopus_query = QueryTranslator.to_scopus(query)
    # Check that TITLE-ABS-KEY wrapper was added
    assert "TITLE-ABS-KEY" in scopus_query
    # Check that hyphenated pre-train* was expanded
    assert '"pre-trained" OR "pre-training"' in scopus_query


def test_translate_to_wos():
    query = '("unlearnable*" OR "adversarial") AND ("defens*" OR "clean")'
    wos_query = QueryTranslator.to_wos(query)
    assert "TS=(" in wos_query


def test_translate_to_ieee():
    query = '("unlearnable*" OR "clean") AND ("defens*" OR "attack*")'
    ieee_query = QueryTranslator.to_ieee(query)
    assert '("All Metadata":"unlearnable*")' in ieee_query
    assert '("All Metadata":"clean")' in ieee_query


def test_translate_to_springer():
    query = '("unlearnable*" OR "clean") AND ("defens*" OR "attack*")'
    springer_query = QueryTranslator.to_springer(query)
    # Asterisks should be removed/expanded
    assert "*" not in springer_query
    assert '"clean"' in springer_query
