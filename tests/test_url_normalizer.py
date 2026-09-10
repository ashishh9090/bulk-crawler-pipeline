"""Unit tests for URL normalization and canonicalization."""

from crawler.url_normalizer import hash_url, normalize_url


def test_lowercase_scheme_and_host():
    raw = "HTTP://Example.COM:80/path/to/PAGE"
    expected = "http://example.com/path/to/PAGE"
    assert normalize_url(raw) == expected


def test_strip_default_ports():
    assert normalize_url("http://example.com:80/test") == "http://example.com/test"
    assert normalize_url("https://example.com:443/test") == "https://example.com/test"
    # Custom ports should remain
    assert normalize_url("http://example.com:8080/test") == "http://example.com:8080/test"


def test_strip_fragments():
    raw = "https://example.com/page#section-2"
    assert normalize_url(raw) == "https://example.com/page"


def test_strip_tracking_parameters():
    raw = "https://example.com/item?id=123&utm_source=twitter&utm_medium=cpc&fbclid=XYZ"
    expected = "https://example.com/item?id=123"
    assert normalize_url(raw) == expected


def test_deterministic_query_parameter_sorting():
    url1 = "https://example.com/search?z=last&a=first&m=middle"
    url2 = "https://example.com/search?m=middle&z=last&a=first"
    assert normalize_url(url1) == "https://example.com/search?a=first&m=middle&z=last"
    assert normalize_url(url1) == normalize_url(url2)


def test_trailing_slash_normalization():
    assert normalize_url("https://example.com/products/") == "https://example.com/products"
    assert normalize_url("https://example.com/") == "https://example.com/"
    assert normalize_url("https://example.com") == "https://example.com/"


def test_hash_url_deterministic():
    u1 = normalize_url("https://example.com/test?b=2&a=1#fragment")
    u2 = normalize_url("https://example.com/test?a=1&b=2")
    assert hash_url(u1) == hash_url(u2)
    assert len(hash_url(u1)) == 64
