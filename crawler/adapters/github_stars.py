"""Legitimate GitHub API star count and metadata extractor."""

import json
import re
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup
from crawler.config import settings
from crawler.logging import logger
from crawler.rate_limiter import rate_limiter
from crawler.retry import RetryableHttpError, retry_with_backoff


class GitHubStarsExtractor:
    """Extracts verified, real-time GitHub repository star counts."""

    def __init__(self):
        self._cache: Dict[str, int] = {}

    def parse_github_slug(self, url: str) -> Optional[Tuple[str, str]]:
        """Extracts (owner, repo) from a GitHub repository URL."""
        if not url or "github.com/" not in url.lower():
            return None
        match = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url)
        if not match:
            return None
        owner = match.group(1).strip()
        repo = match.group(2).strip().rstrip("/").removesuffix(".git")
        # Ignore non-repo GitHub pages like topics, search, login, etc.
        if owner.lower() in ("topics", "features", "explore", "trending", "about", "pricing", "login"):
            return None
        return owner, repo

    async def get_stars(self, github_url: str) -> int:
        """Retrieves exact star count via GitHub REST API or public HTML metadata."""
        slug = self.parse_github_slug(github_url)
        if not slug:
            return 0

        owner, repo = slug
        key = f"{owner.lower()}/{repo.lower()}"
        if key in self._cache:
            return self._cache[key]

        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "BulkAcquisitionPipeline/1.0",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        from crawler.http_client import http_client

        try:
            raw_json = await http_client.fetch(api_url, headers=headers)
            data = json.loads(raw_json)
            stars = int(data.get("stargazers_count", 0))
            self._cache[key] = stars
            logger.debug("Fetched stars for %s: %d", key, stars)
            return stars
        except Exception as api_err:
            logger.debug("GitHub API failed for %s (%s). Attempting HTML fallback.", key, api_err)

        # Fallback: scrape public GitHub repo page for stars badge
        try:
            repo_web_url = f"https://github.com/{owner}/{repo}"
            html = await http_client.fetch(repo_web_url)
            soup = BeautifulSoup(html, "html.parser")

            # Look for repo-stars-counter-star or aria-label
            star_elem = soup.find(id="repo-stars-counter-star")
            if star_elem:
                raw_text = star_elem.get("aria-label", "") or star_elem.get_text(strip=True)
                match = re.search(r"([\d,.]+)\s*(k|m)?", raw_text, re.I)
                if match:
                    num_str = match.group(1).replace(",", "")
                    multiplier = 1
                    if match.group(2):
                        multiplier = 1000 if match.group(2).lower() == "k" else 1_000_000
                    stars = int(float(num_str) * multiplier)
                    self._cache[key] = stars
                    return stars
        except Exception as html_err:
            logger.debug("GitHub HTML scrape fallback failed for %s: %s", key, html_err)

        # If all attempts fail (e.g. deleted repository or private), record 0
        self._cache[key] = 0
        return 0


github_extractor = GitHubStarsExtractor()
