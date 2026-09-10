"""Unit tests for content cleaning and readable text extraction."""

from crawler.signals.content_cleaner import ContentCleaner


def test_noisy_tags_and_chrome_removal():
    noisy_html = """
    <html>
    <head>
        <script>alert('spam');</script>
        <style>.ad { color: red; }</style>
    </head>
    <body>
        <nav><ul><li><a href="/">Home</a></li><li><a href="/news">News</a></li></ul></nav>
        <div id="cookie-banner" class="cookie-consent-modal">Please accept all cookies</div>
        <aside class="sidebar-widget">Check out these sponsored links</aside>
        <main>
            <h1>Major AI Breakthrough Unveiled</h1>
            <p>Researchers have trained a world model capable of interactive real-time simulation.</p>
            <h2>Key Capabilities</h2>
            <ul>
                <li>Zero-shot transfer</li>
                <li>Sub-millisecond inference</li>
            </ul>
        </main>
        <div class="newsletter-signup-box"><form><input type="email"><button>Subscribe</button></form></div>
        <footer><p>&copy; 2026 Tech News Corp</p></footer>
    </body>
    </html>
    """
    cleaned = ContentCleaner.clean_html(noisy_html)
    cleaned_text = ContentCleaner.extract_text(cleaned)

    # Ensure noisy components are gone
    assert "cookie" not in cleaned_text.lower()
    assert "subscribe" not in cleaned_text.lower()
    assert "sponsored" not in cleaned_text.lower()
    assert "2026 Tech News Corp" not in cleaned_text

    # Ensure meaningful content is retained
    assert "Major AI Breakthrough Unveiled" in cleaned_text
    assert "real-time simulation" in cleaned_text
    assert "Zero-shot transfer" in cleaned_text
    assert "Sub-millisecond inference" in cleaned_text


def test_extract_article_content():
    html = """
    <html>
    <head>
        <title>New Open-Weights LLM Released</title>
        <meta name="author" content="Jane Doe">
        <meta name="description" content="A comprehensive review of the new model release.">
    </head>
    <body>
        <article>
            <h1 class="entry-title">New Open-Weights LLM Released</h1>
            <div class="byline">By Jane Doe</div>
            <div class="article-content">
                <p>The open-source community received a massive boost today.</p>
                <p>Weights and training recipes have been publicly uploaded to Hugging Face.</p>
            </div>
        </article>
    </body>
    </html>
    """
    res = ContentCleaner.extract_article_content(
        html,
        selectors={
            "title": "h1.entry-title",
            "author": ".byline",
            "body": ".article-content",
        },
    )
    assert res["title"] == "New Open-Weights LLM Released"
    assert "Jane Doe" in res["author"]
    assert "open-source community" in res["full_text"]
    assert "Weights and training recipes" in res["full_text"]
    assert "comprehensive review" in res["summary"]


def test_extract_job_content():
    html = """
    <html>
    <body>
        <div class="job-container">
            <h1 class="job-title">Staff AI Research Scientist</h1>
            <h2 class="company-name">DeepReason Inc.</h2>
            <div class="location">San Francisco, CA (Hybrid)</div>
            <div class="salary">$250,000 - $320,000 + Equity</div>
            <div class="job-description">
                <p>We are seeking an experienced researcher in reinforcement learning.</p>
                <ul>
                    <li>Ph.D. in Computer Science or equivalent experience</li>
                    <li>Strong publication record at NeurIPS/ICML/ICLR</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """
    res = ContentCleaner.extract_job_content(
        html,
        selectors={
            "title": ".job-title",
            "company": ".company-name",
            "location": ".location",
            "salary": ".salary",
            "body": ".job-description",
        },
    )
    assert res["title"] == "Staff AI Research Scientist"
    assert res["company"] == "DeepReason Inc."
    assert "San Francisco" in res["location"]
    assert "$250,000" in res["salary"]
    assert "reinforcement learning" in res["description_full_text"]
    assert "NeurIPS/ICML/ICLR" in res["description_full_text"]
