"""Sitemap crawler — discovers recipe URLs from site sitemaps."""

from __future__ import annotations

import logging
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .models import RecipeCandidate
from .storage import DredgerStore

logger = logging.getLogger("dredger")


class SitemapCrawler:
    def __init__(self, session: requests.Session, store: DredgerStore,
                 cache_expiry_days: int = 7) -> None:
        self.session = session
        self.store = store
        self.cache_expiry_days = cache_expiry_days

    def find_sitemap(self, base_url: str) -> Optional[str]:
        try:
            response = self.session.get(f"{base_url}/robots.txt", timeout=5)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass

        candidates = [
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap.xml",
            f"{base_url}/wp-sitemap.xml",
            f"{base_url}/post-sitemap.xml",
            f"{base_url}/recipe-sitemap.xml",
        ]

        for url in candidates:
            try:
                response = self.session.head(url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    return response.url
                if response.status_code in [405, 501]:
                    fallback = self.session.get(url, timeout=5, allow_redirects=True, stream=True)
                    fallback.close()
                    if fallback.status_code == 200:
                        return fallback.url
            except Exception:
                pass

        return None

    def fetch_sitemap_urls(self, url: str, depth: int = 0) -> List[str]:
        if depth > 2:
            return []

        try:
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return []

            soup = BeautifulSoup(response.content, "xml")
            all_urls: List[str] = []

            if soup.find("sitemap"):
                sub_maps: list[str] = []
                for sitemap_tag in soup.find_all("sitemap"):
                    loc_tag = sitemap_tag.find("loc", recursive=False)
                    if loc_tag and loc_tag.text:
                        sub_maps.append(loc_tag.text.strip())

                targets = [s for s in sub_maps if "post" in s or "recipe" in s]
                if not targets:
                    targets = sub_maps

                for sub_map in targets[:3]:
                    all_urls.extend(self.fetch_sitemap_urls(sub_map, depth + 1))
                return all_urls

            if soup.find("url"):
                for url_tag in soup.find_all("url"):
                    loc_tag = url_tag.find("loc", recursive=False)
                    if not loc_tag or not loc_tag.text:
                        continue
                    loc = loc_tag.text.strip()
                    if loc.startswith("http://") or loc.startswith("https://"):
                        all_urls.append(loc)
                return all_urls

            return []

        except Exception as exc:
            logger.warning(f"Sitemap parse error {url}: {exc}")
            return []

    def get_urls_for_site(self, site_url: str, force_refresh: bool = False) -> List[RecipeCandidate]:
        if not force_refresh:
            cached = self.store.get_cached_sitemap(site_url, self.cache_expiry_days)
            if cached:
                return [RecipeCandidate(url=url) for url in cached["urls"]]

        sitemap_url = self.find_sitemap(site_url)
        if not sitemap_url:
            return []

        urls = self.fetch_sitemap_urls(sitemap_url)
        self.store.cache_sitemap(site_url, sitemap_url, urls)
        return [RecipeCandidate(url=url) for url in urls]
