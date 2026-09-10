"""Robots.txt politeness checker with async caching."""

import asyncio
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import aiohttp
from crawler.logging import logger


class RobotsChecker:
    """Manages domain-level robots.txt caching and compliance checks."""

    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = timeout_seconds
        self._parsers: Dict[str, Optional[RobotFileParser]] = {}
        self._lock = asyncio.Lock()

    async def get_parser(self, base_url: str, session: aiohttp.ClientSession) -> Optional[RobotFileParser]:
        """Fetches and caches RobotFileParser for a domain."""
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        async with self._lock:
            if domain in self._parsers:
                return self._parsers[domain]

        robots_url = f"{domain}/robots.txt"
        parser = RobotFileParser()

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with session.get(robots_url, timeout=timeout) as response:
                if response.status == 200:
                    content = await response.text(errors="replace")
                    parser.parse(content.splitlines())
                else:
                    # 404 or server error: allow by default
                    parser.allow_all = True
        except Exception as exc:
            logger.debug("Could not fetch robots.txt for %s (%s). Defaulting to allow.", domain, exc)
            parser.allow_all = True

        async with self._lock:
            self._parsers[domain] = parser

        return parser

    async def can_fetch(
        self,
        url: str,
        user_agent: str,
        session: aiohttp.ClientSession,
    ) -> bool:
        """Checks if URL may be fetched according to robots.txt."""
        try:
            parser = await self.get_parser(url, session)
            if not parser:
                return True
            return parser.can_fetch(user_agent, url)
        except Exception:
            return True
