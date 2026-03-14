"""Recipe Dredger — discover and import recipes from curated sites.

Entry point for ``python -m cookdex.recipe_dredger``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import random
import sys
from typing import Optional, Tuple

from .crawler import SitemapCrawler
from .importer import ImportManager
from .rate_limiter import RateLimiter, get_crawl_session
from .sites import DEFAULT_SITES
from .storage import DredgerStore
from .url_utils import canonicalize_url
from .verifier import RecipeVerifier

logger = logging.getLogger("dredger")


# ---------------------------------------------------------------------------
# JSON log formatter
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
        })


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Silence noisy library loggers
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
    logging.getLogger("chardet").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Retry queue processing
# ---------------------------------------------------------------------------

def _process_retry_queue(
    store: DredgerStore,
    verifier: RecipeVerifier,
    importer: ImportManager,
    rate_limiter: RateLimiter,
    max_retry_attempts: int,
) -> None:
    pending = store.get_retry_queue()
    if not pending:
        return

    logger.info(f"Processing retry queue: {len(pending)} URL(s)")

    for entry in pending:
        url = entry["url"]
        url_key = canonicalize_url(url) or url
        attempts = entry["attempts"]

        if attempts >= max_retry_attempts:
            logger.warning(f"Giving up after {attempts} attempts: {url}")
            store.remove_retry(url_key)
            store.add_reject(url_key, "Max retries exceeded")
            continue

        rate_limiter.wait_if_needed(url)
        is_recipe, verify_error, verify_transient = verifier.verify_recipe(url)

        if not is_recipe:
            if verify_transient:
                new_attempts = store.add_retry(url_key, verify_error or "Transient verification failure", increment=True)
                if new_attempts >= max_retry_attempts:
                    logger.warning(f"Max retries reached [verify], rejecting: {url}")
                    store.remove_retry(url_key)
                    store.add_reject(url_key, verify_error or "Max retries exceeded (verify)")
                else:
                    logger.warning(f"Retry queued ({new_attempts}/{max_retry_attempts}) [verify]: {url}")
            else:
                store.remove_retry(url_key)
                store.add_reject(url_key, verify_error or "Verification failed")
            continue

        imported, import_error, import_transient = importer.import_recipe(url)
        if imported:
            store.add_imported(url_key)
            continue

        if import_transient:
            new_attempts = store.add_retry(url_key, import_error or "Transient import failure", increment=True)
            if new_attempts >= max_retry_attempts:
                logger.warning(f"Max retries reached [import], rejecting: {url}")
                store.remove_retry(url_key)
                store.add_reject(url_key, import_error or "Max retries exceeded (import)")
            else:
                logger.warning(f"Retry queued ({new_attempts}/{max_retry_attempts}) [import]: {url}")
        else:
            store.remove_retry(url_key)
            store.add_reject(url_key, import_error or "Import failed")


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    mealie_url = os.environ.get("MEALIE_URL", "").strip()
    mealie_api_key = os.environ.get("MEALIE_API_KEY", "").strip()

    if not mealie_url:
        logger.error("MEALIE_URL is not configured. Set it in Settings > Connection.")
        return 1
    if not mealie_api_key:
        logger.error("MEALIE_API_KEY is not configured. Set it in Settings > Connection.")
        return 1

    target_language = os.environ.get("DREDGER_TARGET_LANGUAGE", "en").strip().lower()
    crawl_delay = float(os.environ.get("DREDGER_CRAWL_DELAY", "2.0"))
    cache_expiry_days = int(os.environ.get("DREDGER_CACHE_EXPIRY_DAYS", "7"))

    dry_run = args.dry_run
    target_count = args.limit
    scan_depth = args.depth
    force_refresh = args.no_cache
    import_workers = max(1, min(args.workers, 4))
    precheck_duplicates = args.precheck
    language_filter = args.language_filter
    max_retry_attempts = args.max_retries
    site_failure_threshold = 3

    store = DredgerStore()
    session = get_crawl_session()
    rate_limiter = RateLimiter(default_delay=crawl_delay)
    crawler = SitemapCrawler(session, store, cache_expiry_days=cache_expiry_days)
    verifier = RecipeVerifier(
        session,
        target_language=target_language,
        language_filter_enabled=language_filter,
    )
    importer = ImportManager(
        mealie_url=mealie_url,
        mealie_api_key=mealie_api_key,
        store=store,
        rate_limiter=rate_limiter,
        dry_run=dry_run,
        precheck_duplicates=precheck_duplicates,
    )

    # Load sites from DB, auto-seed defaults if empty
    sites_list = store.get_enabled_sites()
    if not sites_list:
        seeded = store.seed_defaults(DEFAULT_SITES)
        if seeded:
            logger.info(f"Seeded {seeded} default recipe sites")
        sites_list = store.get_enabled_sites()

    if not sites_list:
        logger.error("No recipe sites configured. Add sites in Settings > Recipe Sources.")
        return 1

    logger.info(f"Recipe Dredger started")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE IMPORT'}")
    logger.info(f"Sites: {len(sites_list)}, Limit: {target_count}/site, Depth: {scan_depth}")
    logger.info(f"Workers: {import_workers}, Language: {target_language if language_filter else 'disabled'}")

    # Process retry queue first
    _process_retry_queue(store, verifier, importer, rate_limiter, max_retry_attempts)

    # Set up concurrent import executor
    import_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    if import_workers > 1 and not dry_run:
        import_executor = concurrent.futures.ThreadPoolExecutor(max_workers=import_workers)

    try:
        random.shuffle(sites_list)

        for site in sites_list:
            logger.info(f"Processing site: {site}")
            site_stats = {"imported": 0, "rejected": 0, "errors": 0}

            raw_candidates = crawler.get_urls_for_site(site, force_refresh=force_refresh)
            if not raw_candidates:
                logger.info(f"No URLs found for {site}")
                continue

            candidates = raw_candidates[:scan_depth]
            random.shuffle(candidates)

            imported_count = 0
            site_failure_streak = 0
            abort_site = False
            pending_imports: dict[concurrent.futures.Future[Tuple[bool, Optional[str], bool]], tuple[str, str]] = {}

            def drain_imports(block: bool = False) -> None:
                nonlocal imported_count, site_failure_streak, abort_site
                if not pending_imports:
                    return
                if block:
                    done, _ = concurrent.futures.wait(
                        pending_imports.keys(),
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                else:
                    done = {f for f in pending_imports if f.done()}

                for future in done:
                    url, url_key = pending_imports.pop(future)
                    try:
                        imported, import_error, import_transient = future.result()
                    except Exception as exc:
                        imported, import_error, import_transient = False, str(exc), False

                    if imported:
                        store.add_imported(url_key)
                        site_stats["imported"] += 1
                        imported_count += 1
                        site_failure_streak = 0
                        continue

                    site_stats["errors"] += 1
                    if import_transient:
                        store.add_retry(url_key, import_error or "Transient import failure", increment=True)
                        logger.warning(f"Retry queued [import]: {url}")
                    else:
                        store.add_reject(url_key, import_error or "Import failed")
                        logger.debug(f"Import failed ({import_error}): {url}")

                    if import_error and import_error.startswith("HTTP 5"):
                        site_failure_streak += 1
                        if site_failure_threshold > 0 and site_failure_streak >= site_failure_threshold:
                            if not abort_site:
                                logger.warning(f"Aborting site due to repeated HTTP 5xx errors (streak={site_failure_streak}): {site}")
                            abort_site = True
                    else:
                        site_failure_streak = 0

            for candidate in candidates:
                if abort_site or imported_count >= target_count:
                    break

                url = candidate.url
                url_key = canonicalize_url(url) or url

                if store.is_known(url_key):
                    continue

                rate_limiter.wait_if_needed(url)
                is_recipe, error, is_transient = verifier.verify_recipe(url)

                if is_recipe:
                    if import_executor is None:
                        imported, import_error, import_transient = importer.import_recipe(url)
                        if imported:
                            store.add_imported(url_key)
                            site_stats["imported"] += 1
                            imported_count += 1
                            site_failure_streak = 0
                        else:
                            site_stats["errors"] += 1
                            if import_transient:
                                store.add_retry(url_key, import_error or "Transient import failure", increment=True)
                            else:
                                store.add_reject(url_key, import_error or "Import failed")
                            if import_error and import_error.startswith("HTTP 5"):
                                site_failure_streak += 1
                                if site_failure_threshold > 0 and site_failure_streak >= site_failure_threshold:
                                    logger.warning(f"Aborting site due to repeated HTTP 5xx errors: {site}")
                                    abort_site = True
                            else:
                                site_failure_streak = 0
                        continue

                    # Concurrent import
                    while pending_imports and imported_count + len(pending_imports) >= target_count:
                        drain_imports(block=True)
                    if imported_count >= target_count:
                        break

                    future = import_executor.submit(importer.import_recipe, url)
                    pending_imports[future] = (url, url_key)
                    drain_imports(block=False)
                else:
                    if is_transient:
                        store.add_retry(url_key, error or "Transient verification failure", increment=True)
                        logger.warning(f"Retry queued [verify]: {url}")
                    else:
                        store.add_reject(url_key, error or "Not a recipe")
                        site_stats["rejected"] += 1

            # Drain remaining concurrent imports
            while pending_imports and imported_count < target_count and not abort_site:
                drain_imports(block=True)
            for future in list(pending_imports):
                future.cancel()
                pending_imports.pop(future, None)

            logger.info(
                f"Site results: {site_stats['imported']} imported, "
                f"{site_stats['rejected']} rejected, {site_stats['errors']} errors"
            )

    finally:
        if import_executor is not None:
            import_executor.shutdown(wait=False, cancel_futures=True)

    # Summary
    logger.info("=" * 50)
    logger.info("Session Summary:")
    logger.info(f"  Total Imported: {store.imported_count()}")
    logger.info(f"  Total Rejected: {store.rejected_count()}")
    logger.info(f"  In Retry Queue: {store.retry_count()}")
    logger.info("=" * 50)
    logger.info("Dredge cycle complete")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recipe Dredger")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Scan without importing")
    parser.add_argument("--limit", type=int, default=50, help="Recipes to import per site")
    parser.add_argument("--depth", type=int, default=1000, help="URLs to scan per site")
    parser.add_argument("--no-cache", action="store_true", default=False, help="Force fresh crawl")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent import workers (1-4)")
    parser.add_argument("--no-precheck", action="store_true", default=False, help="Disable duplicate precheck")
    parser.add_argument("--no-language-filter", action="store_true", default=False, help="Disable language filtering")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retry attempts per URL")
    return parser


def main() -> None:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    # Invert negative flags for clarity
    args.precheck = not args.no_precheck
    args.language_filter = not args.no_language_filter
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
