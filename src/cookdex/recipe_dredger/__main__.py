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
from urllib.parse import urlparse

from .crawler import SitemapCrawler
from .importer import ImportManager
from .rate_limiter import RateLimiter, get_crawl_session
from .sites import DEFAULT_SITES
from .storage import DredgerStore
from .url_utils import canonicalize_url
from .verifier import RecipeVerifier

logger = logging.getLogger("dredger")


# ---------------------------------------------------------------------------
# Logging setup — silence library noise, keep dredger at DEBUG for internal
# use but route all user-facing output through _log() / print().
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
    logging.getLogger("chardet").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _log(tag: str, msg: str) -> None:
    """Print a CookDex-format log line."""
    print(f"[{tag}] {msg}", flush=True)


def _site_label(url: str) -> str:
    """Extract a short label from a site URL."""
    return urlparse(url).hostname or url


# ---------------------------------------------------------------------------
# Retry queue processing
# ---------------------------------------------------------------------------

def _process_retry_queue(
    store: DredgerStore,
    verifier: RecipeVerifier,
    importer: ImportManager,
    rate_limiter: RateLimiter,
    max_retry_attempts: int,
) -> int:
    pending = store.get_retry_queue()
    if not pending:
        return 0

    _log("info", f"Processing retry queue: {len(pending)} URL(s)")
    retried = 0

    for entry in pending:
        url = entry["url"]
        url_key = canonicalize_url(url) or url
        attempts = entry["attempts"]

        if attempts >= max_retry_attempts:
            store.remove_retry(url_key)
            store.add_reject(url_key, "Max retries exceeded")
            continue

        rate_limiter.wait_if_needed(url)
        is_recipe, verify_error, verify_transient = verifier.verify_recipe(url)

        if not is_recipe:
            if verify_transient:
                new_attempts = store.add_retry(url_key, verify_error or "Transient verification failure", increment=True)
                if new_attempts >= max_retry_attempts:
                    store.remove_retry(url_key)
                    store.add_reject(url_key, verify_error or "Max retries exceeded (verify)")
            else:
                store.remove_retry(url_key)
                store.add_reject(url_key, verify_error or "Verification failed")
            continue

        imported, import_error, import_transient = importer.import_recipe(url)
        if imported:
            store.add_imported(url_key)
            retried += 1
            continue

        if import_transient:
            new_attempts = store.add_retry(url_key, import_error or "Transient import failure", increment=True)
            if new_attempts >= max_retry_attempts:
                store.remove_retry(url_key)
                store.add_reject(url_key, import_error or "Max retries exceeded (import)")
        else:
            store.remove_retry(url_key)
            store.add_reject(url_key, import_error or "Import failed")

    return retried


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    mealie_url = os.environ.get("MEALIE_URL", "").strip()
    mealie_api_key = os.environ.get("MEALIE_API_KEY", "").strip()

    if not mealie_url:
        _log("error", "MEALIE_URL is not configured. Set it in Settings > Connection.")
        return 1
    if not mealie_api_key:
        _log("error", "MEALIE_API_KEY is not configured. Set it in Settings > Connection.")
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
            _log("info", f"Seeded {seeded} default recipe sites")
        sites_list = store.get_enabled_sites()

    if not sites_list:
        _log("error", "No recipe sites configured. Add sites in Settings > Recipe Sources.")
        return 1

    mode_label = "DRY RUN" if dry_run else "LIVE"
    lang_label = target_language if language_filter else "off"
    _log("start", f"Recipe Dredger — {mode_label}, {len(sites_list)} sites, limit {target_count}/site, lang={lang_label}")

    # Process retry queue first
    retried = _process_retry_queue(store, verifier, importer, rate_limiter, max_retry_attempts)
    if retried:
        _log("ok", f"Retry queue: {retried} recovered")

    # Set up concurrent import executor
    import_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    if import_workers > 1 and not dry_run:
        import_executor = concurrent.futures.ThreadPoolExecutor(max_workers=import_workers)

    total_sites = len(sites_list)
    grand_imported = 0
    grand_rejected = 0
    grand_errors = 0

    try:
        random.shuffle(sites_list)

        for site_idx, site in enumerate(sites_list, 1):
            label = _site_label(site)
            site_stats = {"imported": 0, "rejected": 0, "errors": 0}

            raw_candidates = crawler.get_urls_for_site(site, force_refresh=force_refresh)
            if not raw_candidates:
                _log("skip", f"[{site_idx}/{total_sites}] {label} — no URLs in sitemap")
                continue

            candidates = raw_candidates[:scan_depth]
            random.shuffle(candidates)

            _log("info", f"[{site_idx}/{total_sites}] {label} — scanning {len(candidates)} URLs")

            imported_count = 0
            checked_count = 0
            skipped_count = 0
            site_failure_streak = 0
            abort_site = False
            pending_imports: dict[concurrent.futures.Future[Tuple[bool, Optional[str], bool]], tuple[str, str]] = {}
            progress_interval = 25

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
                    else:
                        store.add_reject(url_key, import_error or "Import failed")

                    if import_error and import_error.startswith("HTTP 5"):
                        site_failure_streak += 1
                        if site_failure_threshold > 0 and site_failure_streak >= site_failure_threshold:
                            if not abort_site:
                                _log("warn", f"{label} — aborting, repeated HTTP 5xx errors")
                            abort_site = True
                    else:
                        site_failure_streak = 0

            for candidate in candidates:
                if abort_site or imported_count >= target_count:
                    break

                url = candidate.url
                url_key = canonicalize_url(url) or url

                if store.is_known(url_key):
                    skipped_count += 1
                    continue

                rate_limiter.wait_if_needed(url)
                is_recipe, error, is_transient = verifier.verify_recipe(url)
                checked_count += 1

                if checked_count % progress_interval == 0:
                    _log("info", f"[{site_idx}/{total_sites}] {label} — checked {checked_count}, {imported_count} {'found' if dry_run else 'imported'}, {skipped_count} known")

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
                                    _log("warn", f"{label} — aborting, repeated HTTP 5xx errors")
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
                    else:
                        store.add_reject(url_key, error or "Not a recipe")
                        site_stats["rejected"] += 1

            # Drain remaining concurrent imports
            while pending_imports and imported_count < target_count and not abort_site:
                drain_imports(block=True)
            for future in list(pending_imports):
                future.cancel()
                pending_imports.pop(future, None)

            grand_imported += site_stats["imported"]
            grand_rejected += site_stats["rejected"]
            grand_errors += site_stats["errors"]

            parts = []
            if site_stats["imported"]:
                parts.append(f"{site_stats['imported']} {'found' if dry_run else 'imported'}")
            if site_stats["rejected"]:
                parts.append(f"{site_stats['rejected']} rejected")
            if site_stats["errors"]:
                parts.append(f"{site_stats['errors']} errors")
            status = ", ".join(parts) if parts else "nothing new"
            _log("ok", f"[{site_idx}/{total_sites}] {label} — {status}")

    finally:
        if import_executor is not None:
            import_executor.shutdown(wait=False, cancel_futures=True)

    _log("done", f"Dredge complete — {grand_imported} {'found' if dry_run else 'imported'}, {grand_rejected} rejected, {grand_errors} errors")
    print("[summary] " + json.dumps({
        "__title__": "Recipe Dredger",
        "Mode": "Dry Run" if dry_run else "Live Import",
        "Sites Scanned": total_sites,
        "Recipes Found" if dry_run else "Recipes Imported": grand_imported,
        "Rejected": grand_rejected,
        "Errors": grand_errors,
        "Retry Queue": store.retry_count(),
        "Language": lang_label,
    }), flush=True)
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
