"""Unit tests for signal URL canonicalization and hashing."""

from crawler.signals.url_canonicalizer import canonicalize_signal_url, compute_url_hash


def test_strip_tracking_and_feed_parameters():
    raw = "https://techcrunch.com/2026/09/10/ai-agent/?utm_source=feedburner&utm_medium=feed&ref=rss&feed_type=xml"
    expected = "https://techcrunch.com/2026/09/10/ai-agent"
    assert canonicalize_signal_url(raw) == expected


def test_strip_session_and_analytics_ids():
    raw = "https://remoteok.com/remote-jobs/12345?session_id=abcdef123456&_ga=123.456"
    expected = "https://remoteok.com/remote-jobs/12345"
    assert canonicalize_signal_url(raw) == expected


def test_path_normalization_and_fragments():
    raw = "HTTPS://WWW.Example.COM:443//blog//ai-news/#comments"
    expected = "https://www.example.com/blog/ai-news"
    assert canonicalize_signal_url(raw) == expected


def test_query_parameter_sorting():
    url1 = "https://example.com/jobs?tag=ai&location=remote"
    url2 = "https://example.com/jobs?location=remote&tag=ai"
    assert canonicalize_signal_url(url1) == canonicalize_signal_url(url2)
    assert canonicalize_signal_url(url1) == "https://example.com/jobs?location=remote&tag=ai"


def test_compute_url_hash_deterministic():
    url = "https://techcrunch.com/2026/09/10/ai-agent"
    h1 = compute_url_hash(url)
    h2 = compute_url_hash(url)
    assert h1 == h2
    assert len(h1) == 64
