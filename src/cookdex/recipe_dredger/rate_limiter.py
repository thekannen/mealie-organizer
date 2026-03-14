"""Rate limiter with robots.txt crawl-delay compliance."""

from __future__ import annotations

import random
import time
from typing import Dict
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def get_crawl_session() -> requests.Session:
    """Create an HTTP session with retry logic for GET/HEAD requests."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504, 429],
        allowed_methods=["HEAD", "GET"],
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


class RateLimiter:
    def __init__(self, default_delay: float = 2.0, respect_robots: bool = True) -> None:
        self.default_delay = default_delay
        self.respect_robots = respect_robots
        self.last_request: Dict[str, float] = {}
        self.crawl_delays: Dict[str, float] = {}
        self._session = get_crawl_session()

    def _get_domain(self, url: str) -> str:
        return urlparse(url).netloc

    def _get_crawl_delay(self, domain: str) -> float:
        if domain in self.crawl_delays:
            return self.crawl_delays[domain]

        delay = self.default_delay
        if self.respect_robots:
            try:
                response = self._session.get(f"https://{domain}/robots.txt", timeout=5)
                if response.status_code == 200:
                    for line in response.text.splitlines():
                        if line.lower().startswith("crawl-delay:"):
                            try:
                                delay = float(line.split(":", 1)[1].strip())
                                break
                            except ValueError:
                                pass
            except Exception:
                pass

        self.crawl_delays[domain] = delay
        return delay

    def wait_if_needed(self, url: str) -> None:
        domain = self._get_domain(url)
        delay = self._get_crawl_delay(domain)

        if domain in self.last_request:
            elapsed = time.time() - self.last_request[domain]
            if elapsed < delay:
                jitter = random.uniform(0.5, 1.5)
                sleep_time = (delay - elapsed) * jitter
                time.sleep(sleep_time)

        self.last_request[domain] = time.time()
