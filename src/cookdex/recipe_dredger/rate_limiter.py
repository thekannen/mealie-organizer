"""Rate limiter with robots.txt crawl-delay compliance."""

from __future__ import annotations

import random
import time
from typing import Dict
from urllib import robotparser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..url_security import request_with_url_validation

_MIN_DELAY: float = 1.0  # hard floor — cannot be bypassed by config

_VERSION = "unknown"
try:
    from importlib.metadata import version as _pkg_version

    _VERSION = _pkg_version("cookdex")
except Exception:
    pass

USER_AGENT = f"CookDex/{_VERSION} (+https://github.com/thekannen/CookDex)"


def _robot_entry_applies(user_agent: str, entry_user_agents: list[str]) -> bool:
    user_agent_token = user_agent.split("/")[0].lower()
    for agent in entry_user_agents:
        if agent == "*":
            return True
        if agent.lower() in user_agent_token:
            return True
    return False


def _parse_float_crawl_delay(raw_value: str) -> float | None:
    try:
        delay = float(raw_value.strip())
    except ValueError:
        return None
    if delay < 0:
        return None
    return delay


def _float_crawl_delay_for_user_agent(lines: list[str], user_agent: str) -> float | None:
    entries: list[tuple[list[str], float | None]] = []
    default_entry: tuple[list[str], float | None] | None = None
    agents: list[str] = []
    delay: float | None = None
    saw_directive = False

    def flush() -> None:
        nonlocal agents, delay, saw_directive, default_entry
        if not agents or not saw_directive:
            agents = []
            delay = None
            saw_directive = False
            return
        entry = (agents, delay)
        if "*" in agents:
            if default_entry is None:
                default_entry = entry
        else:
            entries.append(entry)
        agents = []
        delay = None
        saw_directive = False

    for raw_line in lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            flush()
            continue
        key, sep, raw_value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = raw_value.strip()
        if key == "user-agent":
            if saw_directive:
                flush()
            agents.append(value)
            continue
        if not agents:
            continue
        if key == "crawl-delay":
            parsed_delay = _parse_float_crawl_delay(value)
            if parsed_delay is not None:
                delay = parsed_delay
            saw_directive = True
        elif key in {"allow", "disallow", "request-rate"}:
            saw_directive = True

    flush()

    for entry_agents, entry_delay in entries:
        if _robot_entry_applies(user_agent, entry_agents):
            return entry_delay
    if default_entry is not None:
        return default_entry[1]
    return None


def get_crawl_session() -> requests.Session:
    """Create an HTTP session with retry logic for GET/HEAD requests."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
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
        self.default_delay = max(default_delay, _MIN_DELAY)
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
                response = request_with_url_validation(
                    self._session,
                    "GET",
                    f"https://{domain}/robots.txt",
                    timeout=5,
                )
                if response.status_code == 200:
                    robots_lines = response.text.splitlines()
                    parser = robotparser.RobotFileParser(f"https://{domain}/robots.txt")
                    parser.parse(robots_lines)
                    robots_delay = _float_crawl_delay_for_user_agent(robots_lines, USER_AGENT)
                    if robots_delay is None:
                        robots_delay = parser.crawl_delay(USER_AGENT)
                    if robots_delay is not None:
                        delay = max(delay, float(robots_delay), _MIN_DELAY)
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
