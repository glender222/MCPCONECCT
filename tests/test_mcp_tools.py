"""
Integration tests for MCP tools.
"""
from mcp_server.server import mcp_server
from mcp_server.tools.auth_tools import configure_burp_proxy, configure_auth, get_database_status
from mcp_server.tools.validation_tools import validate_search_string, translate_search_string


def test_mcp_validation_tools():
    # Test Scopus validation
    res = validate_search_string("scopus", 'TITLE-ABS-KEY ( "unlearnable*" AND "pre-train*" )')
    assert res["is_valid"] is True
    assert any("pre-train*" in w for w in res["warnings"])

    # Test IEEE 10 wildcard ceiling
    res_ieee_ok = validate_search_string("ieee", '("All Metadata":"test1*") AND ("All Metadata":"test2*")')
    assert res_ieee_ok["is_valid"] is True

    # Test translation
    translations = translate_search_string('("unlearnable*" OR "adversarial") AND ("defens*" OR "clean")')
    assert "scopus" in translations
    assert "ieee" in translations
    assert "wos" in translations
    assert "springer" in translations


def test_burp_proxy_configuration():
    # Toggle Burp proxy
    res = configure_burp_proxy(enabled=True, proxy_url="http://127.0.0.1:8080", disable_ssl_verification=True)
    assert res["burp_proxy_enabled"] is True
    assert res["proxy_url"] == "http://127.0.0.1:8080"

    status = get_database_status()
    assert status["burp_proxy_enabled"] is True
    assert "scopus" in status["databases"]
    assert "ieee" in status["databases"]
    assert "wos" in status["databases"]
    assert "springer" in status["databases"]

    # Disable proxy
    res_off = configure_burp_proxy(enabled=False)
    assert res_off["burp_proxy_enabled"] is False
