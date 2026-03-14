"""Recipe importer — sends verified URLs to Mealie for scraping."""

from __future__ import annotations

import logging
import threading
from typing import Optional, Set, Tuple

import requests
from requests.adapters import HTTPAdapter

from .patterns import TRANSIENT_HTTP_CODES
from .rate_limiter import RateLimiter
from .storage import DredgerStore
from .url_utils import canonicalize_url

logger = logging.getLogger("dredger")


class ImportManager:
    def __init__(
        self,
        mealie_url: str,
        mealie_api_key: str,
        store: DredgerStore,
        rate_limiter: RateLimiter,
        dry_run: bool = True,
        precheck_duplicates: bool = True,
        import_timeout: int = 20,
    ) -> None:
        self.mealie_url = mealie_url.rstrip("/")
        self.mealie_api_key = mealie_api_key
        self.store = store
        self.rate_limiter = rate_limiter
        self.dry_run = dry_run
        self.precheck_duplicates = precheck_duplicates
        self.import_timeout = import_timeout

        # Import session: no urllib3-level retries; retry logic is handled
        # by the dredger's own retry queue.
        self.import_session = requests.Session()
        self.import_session.mount("http://", HTTPAdapter(max_retries=0))
        self.import_session.mount("https://", HTTPAdapter(max_retries=0))

        self._endpoint_candidates = [
            "/api/recipes/create/url",
            "/api/recipes/create-url",
        ]
        self._import_path: Optional[str] = None
        self._known_source_urls: Set[str] = set()
        self._source_index_loaded = False
        self._source_index_failed = False
        self._source_lock = threading.Lock()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.mealie_api_key}"}

    def _compact_error_body(self, text: str) -> str:
        body = text.strip().replace("\n", " ")
        if len(body) > 180:
            body = f"{body[:177]}..."
        return body

    def _is_permanent_mealie_500(self, body: str) -> bool:
        lowered = body.lower()
        return "unknown error" in lowered or "noresultfound" in lowered or "no result found" in lowered

    def _extract_source_url(self, recipe: dict) -> str:
        for key in ["orgURL", "originalURL", "source"]:
            value = recipe.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _load_existing_sources(self) -> None:
        if self._source_index_loaded or self._source_index_failed:
            return

        source_urls: Set[str] = set()
        page = 1
        try:
            while True:
                response = self.import_session.get(
                    f"{self.mealie_url}/api/recipes",
                    headers=self._headers,
                    params={"page": page, "perPage": 1000},
                    timeout=self.import_timeout,
                )
                if response.status_code != 200:
                    logger.warning(f"Duplicate precheck disabled: recipe list HTTP {response.status_code}")
                    self._source_index_failed = True
                    return

                payload = response.json()
                if not isinstance(payload, dict):
                    self._source_index_failed = True
                    return

                items = payload.get("items", [])
                if not isinstance(items, list) or not items:
                    break

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    source_url = self._extract_source_url(item)
                    canonical = canonicalize_url(source_url)
                    if canonical:
                        source_urls.add(canonical)
                page += 1

            self._known_source_urls = source_urls
            self._source_index_loaded = True
            logger.debug(f"Duplicate precheck index loaded: {len(source_urls)} entries")
        except Exception as exc:
            logger.warning(f"Duplicate precheck unavailable: {exc}")
            self._source_index_failed = True

    def _is_duplicate_source(self, url: str) -> bool:
        if not self.precheck_duplicates:
            return False
        with self._source_lock:
            self._load_existing_sources()
            if self._source_index_failed:
                return False
            canonical = canonicalize_url(url)
            if canonical and canonical in self._known_source_urls:
                logger.debug(f"Duplicate source URL, skipping: {url}")
                return True
        return False

    def import_recipe(self, url: str) -> Tuple[bool, Optional[str], bool]:
        """Import a recipe URL into Mealie.

        Returns (success, error_message, is_transient_error).
        """
        if self.dry_run:
            logger.debug(f"[DRY RUN] Would import: {url}")
            return True, None, False

        try:
            if self._is_duplicate_source(url):
                return True, None, False

            candidate_paths = list(self._endpoint_candidates)
            if self._import_path in candidate_paths:
                candidate_paths.remove(self._import_path)
                candidate_paths.insert(0, self._import_path)

            endpoint_error = None
            for path in candidate_paths:
                response = self.import_session.post(
                    f"{self.mealie_url}{path}",
                    headers=self._headers,
                    json={"url": url},
                    timeout=self.import_timeout,
                )

                if response.status_code in [200, 201, 202]:
                    if self._import_path != path:
                        self._import_path = path
                        logger.info(f"Using import endpoint: {path}")
                    canonical = canonicalize_url(url)
                    if canonical:
                        with self._source_lock:
                            self._known_source_urls.add(canonical)
                    logger.debug(f"Imported: {url}")
                    return True, None, False

                if response.status_code == 409:
                    if self._import_path != path:
                        self._import_path = path
                    canonical = canonicalize_url(url)
                    if canonical:
                        with self._source_lock:
                            self._known_source_urls.add(canonical)
                    logger.debug(f"Duplicate (already in Mealie): {url}")
                    return True, None, False

                if response.status_code in [404, 405]:
                    endpoint_error = f"HTTP {response.status_code}"
                    continue

                if response.status_code in TRANSIENT_HTTP_CODES:
                    body = self._compact_error_body(response.text)
                    if response.status_code == 500 and body and self._is_permanent_mealie_500(body):
                        return False, f"HTTP {response.status_code} - {body}", False
                    return False, f"HTTP {response.status_code}" + (f" - {body}" if body else ""), True

                body = self._compact_error_body(response.text)
                return False, f"HTTP {response.status_code}" + (f" - {body}" if body else ""), False

            return False, endpoint_error or "No compatible Mealie import endpoint found", False

        except requests.exceptions.Timeout as exc:
            return False, f"Timeout: {exc}", True
        except requests.exceptions.ConnectionError as exc:
            return False, f"Connection error: {exc}", True
        except requests.exceptions.RequestException as exc:
            return False, f"Request error: {exc}", True
        except Exception as exc:
            return False, str(exc), False
