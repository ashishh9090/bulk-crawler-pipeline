"""Content extraction and HTML cleaning engine for noisy web pages."""

import re
from typing import Any, Dict, List, Optional
import warnings
from bs4 import BeautifulSoup, Comment, NavigableString, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

NOISY_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "button",
    "form",
    "nav",
    "header",
    "footer",
    "aside",
    "dialog",
    "canvas",
    "audio",
    "video",
    "object",
    "embed",
}

NOISY_CLASS_OR_ID_PATTERNS = re.compile(
    r"(cookie|gdpr|banner|popup|modal|advert|sponsor|promo|social|share|widget|newsletter|subscribe|signup|related|comments)",
    re.IGNORECASE,
)


class ContentCleaner:
    """Removes web chrome, ads, and widgets while preserving core readable content."""

    @staticmethod
    def clean_html(html_text: str, root_selector: Optional[str] = None) -> BeautifulSoup:
        """Parses and strips noisy HTML components."""
        soup = BeautifulSoup(html_text, "lxml")

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove noisy tags
        for tag_name in NOISY_TAGS:
            for el in soup.find_all(tag_name):
                el.decompose()

        # Remove elements with noisy classes or IDs
        for el in soup.find_all(True):
            if not isinstance(el, Tag) or not getattr(el, "attrs", None):
                continue
            el_id = str(el.attrs.get("id") or "")
            raw_classes = el.attrs.get("class", [])
            el_classes = " ".join(raw_classes) if isinstance(raw_classes, list) else str(raw_classes or "")
            if NOISY_CLASS_OR_ID_PATTERNS.search(el_id) or NOISY_CLASS_OR_ID_PATTERNS.search(el_classes):
                # Don't delete body or main
                if el.name not in ("body", "main", "html"):
                    el.decompose()

        if root_selector:
            root = soup.select_one(root_selector)
            if root:
                return BeautifulSoup(str(root), "lxml")

        return soup

    @classmethod
    def extract_text(cls, soup_or_tag: Tag | BeautifulSoup) -> str:
        """Extracts clean markdown-like text preserving headings and paragraphs."""
        lines: List[str] = []

        def _traverse(node: Tag | NavigableString):
            if isinstance(node, NavigableString):
                text = str(node).strip()
                if text:
                    lines.append(text)
                return

            if isinstance(node, Tag):
                name = node.name.lower()
                if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    prefix = "#" * int(name[1]) + " "
                    inner_text = node.get_text(separator=" ", strip=True)
                    if inner_text:
                        lines.append(f"\n{prefix}{inner_text}\n")
                    return
                elif name == "p":
                    inner_text = node.get_text(separator=" ", strip=True)
                    if inner_text:
                        lines.append(f"\n{inner_text}\n")
                    return
                elif name == "li":
                    inner_text = node.get_text(separator=" ", strip=True)
                    if inner_text:
                        lines.append(f"- {inner_text}")
                    return
                elif name in ("div", "section", "article"):
                    for child in node.children:
                        _traverse(child)
                    lines.append("\n")
                    return
                elif name == "br":
                    lines.append("\n")
                    return

                for child in node.children:
                    _traverse(child)

        _traverse(soup_or_tag)

        # Collapse excess empty lines
        raw_text = "\n".join(lines)
        raw_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()
        # Fallback if structural traversal was empty but raw text exists
        if not raw_text:
            raw_text = soup_or_tag.get_text(separator="\n", strip=True)
            raw_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()

        return raw_text

    @classmethod
    def extract_article_content(
        cls,
        html_text: str,
        selectors: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extracts title, author, date, and full readable body text."""
        selectors = selectors or {}
        soup = BeautifulSoup(html_text, "lxml")

        # Extract title
        title = ""
        if selectors.get("title"):
            title_el = soup.select_one(selectors["title"])
            if title_el:
                title = title_el.get_text(strip=True)
        if not title:
            og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.title:
                title = soup.title.get_text(strip=True)

        # Extract author
        author = None
        if selectors.get("author"):
            author_el = soup.select_one(selectors["author"])
            if author_el:
                author = author_el.get_text(strip=True)
        if not author:
            author_meta = (
                soup.find("meta", attrs={"name": "author"})
                or soup.find("meta", property="article:author")
                or soup.find("meta", attrs={"name": "byl"})
            )
            if author_meta and author_meta.get("content"):
                author = author_meta["content"].strip()

        # Extract body text
        cleaned_soup = cls.clean_html(html_text)
        body_selector = selectors.get("body")
        target_container = None
        if body_selector:
            target_container = cleaned_soup.select_one(body_selector)
        if not target_container:
            target_container = cleaned_soup.find("article") or cleaned_soup.find("main") or cleaned_soup.body or cleaned_soup

        full_text = cls.extract_text(target_container)

        # Extract excerpt / summary
        summary = None
        desc_meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if desc_meta and desc_meta.get("content"):
            summary = desc_meta["content"].strip()

        return {
            "title": title,
            "author": author,
            "full_text": full_text,
            "summary": summary,
        }

    @classmethod
    def extract_job_content(
        cls,
        html_text: str,
        selectors: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extracts job title, company, location, salary, employment type, and full description."""
        selectors = selectors or {}
        soup = BeautifulSoup(html_text, "lxml")

        # Title
        title = ""
        if selectors.get("title"):
            el = soup.select_one(selectors["title"])
            if el:
                title = el.get_text(strip=True)
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.title:
                title = soup.title.get_text(strip=True)

        # Company
        company = ""
        if selectors.get("company"):
            el = soup.select_one(selectors["company"])
            if el:
                company = el.get_text(strip=True)
        if not company:
            site_meta = soup.find("meta", property="og:site_name")
            if site_meta and site_meta.get("content"):
                company = site_meta["content"].strip()

        # Location
        location = None
        if selectors.get("location"):
            el = soup.select_one(selectors["location"])
            if el:
                location = el.get_text(strip=True)

        # Salary
        salary = None
        if selectors.get("salary"):
            el = soup.select_one(selectors["salary"])
            if el:
                salary = el.get_text(strip=True)

        # Cleaned body
        cleaned_soup = cls.clean_html(html_text)
        body_selector = selectors.get("body")
        target_container = None
        if body_selector:
            target_container = cleaned_soup.select_one(body_selector)
        if not target_container:
            target_container = cleaned_soup.find("main") or cleaned_soup.find("article") or cleaned_soup.body or cleaned_soup

        full_text = cls.extract_text(target_container)

        return {
            "title": title,
            "company": company or "Unknown Company",
            "location": location,
            "salary": salary,
            "description_full_text": full_text,
        }
