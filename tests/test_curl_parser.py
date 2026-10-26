"""
Unit tests for Burp Suite cURL parser.
"""
from core.http_client import parse_curl_command


def test_parse_burp_curl():
    curl_sample = """curl -i -s -k -X 'POST' \
    -H 'Host: ieeexplore.ieee.org' \
    -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64)' \
    -H 'Accept: application/json' \
    -H 'Cookie: JSESSIONID=abc123456; WLS_COOKIE=987654321; opt_out=false' \
    --data-raw '{"queryText":"test"}' \
    'https://ieeexplore.ieee.org/rest/search'"""

    parsed = parse_curl_command(curl_sample)
    assert parsed["url"] == "https://ieeexplore.ieee.org/rest/search"
    assert parsed["method"] == "POST"
    assert parsed["headers"]["Host"] == "ieeexplore.ieee.org"
    assert parsed["headers"]["User-Agent"] == "Mozilla/5.0 (X11; Linux x86_64)"
    assert parsed["cookies"]["JSESSIONID"] == "abc123456"
    assert parsed["cookies"]["WLS_COOKIE"] == "987654321"
    assert parsed["cookies"]["opt_out"] == "false"
