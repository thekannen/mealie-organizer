import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from .config import config_value, env_or_config


def require_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise ValueError(f"Invalid value for '{field}': expected integer-like, got {type(value).__name__}")


def require_float(value: object, field: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError(f"Invalid value for '{field}': expected float-like, got {type(value).__name__}")


def parse_json_response(result_text):
    """Parse JSON from an LLM response with progressive cleaning stages."""
    if not result_text or not isinstance(result_text, str):
        return None

    trimmed = result_text.strip()

    # Stage 0: try raw text directly (fast path for well-formed responses).
    result = _parse_stage(trimmed)
    if result is not None:
        return result

    # Stage 1: strip markdown code fences.
    defenced = re.sub(r"^```(?:json)?\s*\n?", "", trimmed, count=1, flags=re.IGNORECASE)
    defenced = re.sub(r"\n?\s*```\s*$", "", defenced).strip()
    if defenced != trimmed:
        result = _parse_stage(defenced)
        if result is not None:
            return result

    # Stage 2: extract outermost JSON array/object from surrounding prose.
    text = defenced
    extracted = _extract_json_block(text)
    if extracted is not None and extracted != text:
        result = _parse_stage(extracted)
        if result is not None:
            return result
        text = extracted

    # Stage 3: fix smart (curly) double quotes and trailing commas.
    cleaned = _fix_smart_quotes(text)
    cleaned = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    result = _parse_stage(cleaned)
    if result is not None:
        return result

    # Stage 4: quote bare keys and replace single-quoted strings.
    fixed = _replace_single_quoted_strings(_quote_bare_keys(cleaned))
    if fixed != cleaned:
        result = _parse_stage(fixed)
        if result is not None:
            return result

    # Stage 5: attempt to repair truncated JSON.
    repaired = _repair_truncated_json(fixed)
    if repaired is not None:
        result = _parse_stage(repaired)
        if result is not None:
            return result

    return None


def _try_json_loads(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _unwrap_if_needed(parsed):
    """If parsed is a single-key dict wrapping a list, unwrap it.

    Handles OpenAI json_object mode returning {"results": [...]} instead of [...].
    """
    if isinstance(parsed, dict) and len(parsed) == 1:
        value = next(iter(parsed.values()))
        if isinstance(value, list):
            return value
    return parsed


def _parse_stage(text):
    result = _try_json_loads(text)
    if result is not None:
        return _unwrap_if_needed(result)
    return None


def _extract_json_block(text):
    """Find the outermost JSON array or object using bracket-depth counting.

    Tries array first. If the first JSON-significant character is '[' but the
    array is incomplete (truncated), returns None so truncation repair can run.
    """
    first_bracket = text.find("[")
    first_brace = text.find("{")

    pairs = [("[", "]"), ("{", "}")]
    # If '[' appears before '{', only try array extraction so truncated arrays
    # are not short-circuited by a complete inner object.
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        pairs = [("[", "]")]

    for open_char, close_char in pairs:
        start = text.find(open_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _fix_smart_quotes(text):
    """Replace curly double-quotes with straight double-quotes.

    Single curly quotes (apostrophes) are left alone to avoid corrupting values.
    """
    return text.replace("\u201c", '"').replace("\u201d", '"')


def _quote_bare_keys(text):
    """Quote unquoted JSON object keys without corrupting already-quoted keys."""
    return re.sub(r'(?<=[{\[,])\s*(\w+)\s*:', r' "\1":', text)


def _replace_single_quoted_strings(text):
    """Replace single-quoted JSON strings with double-quoted ones."""
    return re.sub(r"'((?:[^'\\]|\\.)*)'", r'"\1"', text)


def _repair_truncated_json(text):
    """Close unclosed brackets/braces in JSON truncated by token limits."""
    if not text or text[0] not in ("[", "{"):
        return None

    stack = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("[", "{"):
            stack.append("]" if ch == "[" else "}")
        elif ch in ("]", "}"):
            if stack and stack[-1] == ch:
                stack.pop()

    if not stack:
        return None  # already balanced

    # Trim back to last complete value boundary if we're mid-string.
    base = text
    if in_string:
        last_quote = base.rfind('"')
        if last_quote >= 0:
            base = base[:last_quote]

    base = base.rstrip().rstrip(",")
    return base + "".join(reversed(stack))


class MealieCategorizer:
    def __init__(
        self,
        mealie_url,
        mealie_api_key,
        batch_size,
        max_workers,
        replace_existing,
        cache_file,
        query_text,
        provider_name,
        target_mode="missing-either",
        tag_max_name_length=24,
        tag_min_usage=0,
        dry_run=False,
    ):
        self.mealie_url = mealie_url.rstrip("/")
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.replace_existing = replace_existing
        self.cache_file = Path(cache_file)
        self.query_text = query_text
        self.provider_name = provider_name
        self.target_mode = target_mode
        self.tag_max_name_length = tag_max_name_length
        self.tag_min_usage = tag_min_usage
        self.dry_run = dry_run
        self.query_retries = max(
            1,
            require_int(
                env_or_config("QUERY_RETRIES", "categorizer.query_retries", 3, int),
                "categorizer.query_retries",
            ),
        )
        self.query_retry_base_seconds = require_float(
            env_or_config("QUERY_RETRY_BASE_SECONDS", "categorizer.query_retry_base_seconds", 1.25, float),
            "categorizer.query_retry_base_seconds",
        )
        self.headers = {
            "Authorization": f"Bearer {mealie_api_key}",
            "Content-Type": "application/json",
        }

        self.progress = {"done": 0, "total": 0, "start": time.time()}
        self.progress_lock = threading.Lock()
        self.progress_stop_event = threading.Event()
        self.cache_lock = threading.Lock()
        self.print_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.cache_enabled = True
        self.stats = {
            "query_retry_warnings": 0,
            "query_failures": 0,
            "excluded_tag_candidates": 0,
            "cached_skipped": 0,
            "batch_parse_failures": 0,
            "fallback_batches": 0,
            "per_recipe_fallback_attempts": 0,
            "per_recipe_no_classification": 0,
            "unknown_slug_count": 0,
            "model_missing_entry_count": 0,
            "recipes_updated": 0,
            "recipes_planned": 0,
            "recipes_no_change": 0,
            "update_failures": 0,
            "categories_added": 0,
            "tags_added": 0,
            "tools_added": 0,
        }
        self.cache = self.load_cache()

    @staticmethod
    def _resolve_next_url(current_url, next_link):
        if not isinstance(next_link, str) or not next_link:
            return None
        if next_link.lower().startswith(("http://", "https://")):
            return next_link

        if next_link.startswith("/"):
            base = urlsplit(current_url)
            rel = urlsplit(next_link)
            path = rel.path
            # Mealie can return '/recipes?...' even when requests are sent to '/api/recipes?...'.
            if base.path.startswith("/api/") and not path.startswith("/api/"):
                path = f"/api{path}"
            return urlunsplit((base.scheme, base.netloc, path, rel.query, rel.fragment))

        return urljoin(current_url, next_link)

    def _get_paginated(self, url, timeout=60):
        items = []
        next_url = url

        while next_url:
            response = requests.get(next_url, headers=self.headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list):
                return data if not items else items + data
            if not isinstance(data, dict):
                return data

            page_items = data.get("items")
            if page_items is None:
                return data
            if not isinstance(page_items, list):
                return page_items

            items.extend(page_items)
            next_url = self._resolve_next_url(next_url, data.get("next"))

        return items

    def load_cache(self):
        if self.cache_file.exists():
            try:
                with self.cache_file.open("r", encoding="utf-8") as f:
                    try:
                        return json.load(f)
                    except Exception:
                        return {}
            except OSError as exc:
                self.cache_enabled = False
                self.log(f"[warn] Cache disabled: cannot read '{self.cache_file}': {exc}")
                return {}
        return {}

    def save_cache(self):
        if not self.cache_enabled:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except OSError as exc:
            self.cache_enabled = False
            self.log(f"[warn] Cache disabled: cannot write '{self.cache_file}': {exc}")

    def set_progress_total(self, total):
        with self.progress_lock:
            self.progress.update(total=total, done=0, start=time.time())
        self.progress_stop_event.clear()

    def advance_progress(self, count):
        if not count:
            return
        with self.progress_lock:
            self.progress["done"] += count

    def progress_snapshot(self):
        with self.progress_lock:
            return self.progress["done"], self.progress["total"], self.progress["start"]

    def increment_stat(self, key, amount=1):
        if amount == 0:
            return
        with self.stats_lock:
            self.stats[key] = self.stats.get(key, 0) + amount

    def stats_snapshot(self):
        with self.stats_lock:
            return dict(self.stats)

    def reset_stats(self):
        with self.stats_lock:
            for key in self.stats:
                self.stats[key] = 0

    def log(self, message):
        with self.print_lock:
            print(message, flush=True)

    def render_progress_line(self, done, total, start_time):
        elapsed = max(time.time() - start_time, 1e-9)
        rate = done / elapsed
        remaining = (max(total - done, 0) / rate) if rate else float("inf")
        eta = f"{(remaining / 60):.1f} min" if rate else "inf min"
        return f"[progress] {done}/{total} ({rate:.2f}/s) ETA: {eta}"

    def eta_reporter(self):
        last_done = -1
        while True:
            if self.progress_stop_event.is_set():
                break
            done, total, start_time = self.progress_snapshot()
            if total == 0:
                break
            if done != last_done:
                self.log(self.render_progress_line(done, total, start_time))
                last_done = done
            if done >= total:
                break
            self.progress_stop_event.wait(5)

    def print_summary(self):
        done, total, start_time = self.progress_snapshot()
        elapsed = max(time.time() - start_time, 1e-9)
        rate = done / elapsed if elapsed else 0.0
        stats = self.stats_snapshot()
        self.log("[summary] Run Metrics")
        self.log(
            "[summary] "
            f"recipes={done}/{total} updated={stats['recipes_updated']} planned={stats['recipes_planned']} "
            f"unchanged={stats['recipes_no_change']} cached_skipped={stats['cached_skipped']} "
            f"unclassified={stats['per_recipe_no_classification']}"
        )
        self.log(
            "[summary] "
            f"retries={stats['query_retry_warnings']} exhausted_queries={stats['query_failures']} "
            f"batch_parse_failures={stats['batch_parse_failures']} fallback_batches={stats['fallback_batches']} "
            f"per_recipe_fallbacks={stats['per_recipe_fallback_attempts']}"
        )
        self.log(
            "[summary] "
            f"categories_added={stats['categories_added']} tags_added={stats['tags_added']} tools_added={stats['tools_added']} "
            f"update_failures={stats['update_failures']} "
            f"unknown_slugs={stats['unknown_slug_count']} model_missing_entries={stats['model_missing_entry_count']} "
            f"excluded_tag_candidates={stats['excluded_tag_candidates']}"
        )
        self.log(f"[summary] duration={(elapsed / 60):.1f} min avg_rate={rate:.2f}/s")

    def get_all_recipes(self):
        return self._get_paginated(f"{self.mealie_url}/recipes?perPage=1000", timeout=60)

    def get_all_categories(self):
        return self._get_paginated(f"{self.mealie_url}/organizers/categories?perPage=1000", timeout=60)

    def get_all_tags(self):
        return self._get_paginated(f"{self.mealie_url}/organizers/tags?perPage=1000", timeout=60)

    @staticmethod
    def _format_recipe_lines(recipes):
        lines = ""
        for recipe in recipes:
            ingredients = ", ".join(i.get("title", "") for i in recipe.get("ingredients", [])[:10])
            lines += (
                f"\n- slug={recipe.get('slug')} | name=\"{recipe.get('name', '')}\" | ingredients: {ingredients}"
            )
        return lines

    @staticmethod
    def _single_organizer_prompt(recipes, field, role, names, example, recipe_lines):
        names_text = "\n".join(f"- {name}" for name in names)
        return f"""
You are a food recipe {role}.

Select one or more applicable {field} for each recipe from THIS LIST ONLY:
{names_text}

Return ONLY valid JSON array like:
[
  {{"slug": "recipe-slug", {example}}}
]

If absolutely nothing matches, use an empty array. No commentary.

Recipes:
{recipe_lines}""".strip()

    @classmethod
    def make_prompt(cls, recipes, category_names, tag_names, tool_names):
        categories_text = "\n".join(f"- {name}" for name in category_names)
        tags_text = "\n".join(f"- {name}" for name in tag_names)
        tools_text = "\n".join(f"- {name}" for name in tool_names)
        recipe_lines = cls._format_recipe_lines(recipes)
        return f"""
You are a food recipe classifier.

For each recipe below:
1) Select one or more matching categories FROM THIS LIST ONLY.
2) Select one or more relevant tags FROM THIS LIST ONLY. Use an empty array ONLY if nothing fits.
3) Select one or more relevant kitchen tools FROM THIS LIST ONLY. Use an empty array ONLY if nothing fits.

Return results ONLY as valid JSON array like:
[
  {{"slug": "recipe-slug", "categories": ["Dinner"], "tags": ["Quick"], "tools": ["Cast Iron Skillet"]}}
]

If nothing matches, use empty arrays. Do not invent new names. No extra commentary.

Categories:
{categories_text}

Tags:
{tags_text}

Tools:
{tools_text}

Recipes:
{recipe_lines}""".strip()

    @classmethod
    def make_category_prompt(cls, recipes, category_names):
        return cls._single_organizer_prompt(
            recipes, "categories", "category selector", category_names,
            '"categories": ["Dinner"]', cls._format_recipe_lines(recipes),
        )

    @classmethod
    def make_tag_prompt(cls, recipes, tag_names):
        return cls._single_organizer_prompt(
            recipes, "tags", "tagging assistant", tag_names,
            '"tags": ["Quick", "Weeknight"]', cls._format_recipe_lines(recipes),
        )

    @classmethod
    def make_tool_prompt(cls, recipes, tool_names):
        return cls._single_organizer_prompt(
            recipes, "tools", "kitchen tool selector", tool_names,
            '"tools": ["Dutch Oven", "Immersion Blender"]', cls._format_recipe_lines(recipes),
        )

    def get_all_tools(self):
        try:
            return self._get_paginated(f"{self.mealie_url}/organizers/tools?perPage=1000", timeout=60)
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is None or response.status_code != 404:
                raise
        return self._get_paginated(f"{self.mealie_url}/tools?perPage=1000", timeout=60)

    def safe_query_with_retry(self, prompt_text, retries=None):
        attempts = retries if retries is not None else self.query_retries
        for attempt in range(attempts):
            result = self.query_text(prompt_text)
            if result:
                parsed = parse_json_response(result)
                if parsed is not None:
                    return parsed
                snippet = result[:200].replace("\n", "\\n")
                if len(result) > 200:
                    snippet += f"... ({len(result)} chars total)"
                reason = f"invalid JSON in response: {snippet}"
            else:
                reason = "empty or error response from provider"
            self.log(f"[warn] Retry {attempt + 1}/{attempts} failed: {reason}")
            self.increment_stat("query_retry_warnings")
            if attempt < attempts - 1:
                sleep_for = (self.query_retry_base_seconds * (2**attempt)) + random.uniform(0, 0.75)
                time.sleep(sleep_for)
        self.increment_stat("query_failures")
        return None

    @staticmethod
    def build_tag_usage(recipes):
        usage = {}
        for recipe in recipes:
            for tag in recipe.get("tags") or []:
                name = (tag.get("name") or "").strip()
                if name:
                    usage[name] = usage.get(name, 0) + 1
        return usage

    def filter_tag_candidates(self, tags, recipes):
        usage = self.build_tag_usage(recipes)
        noisy_phrases = config_value(
            "categorizer.tag_noisy_phrases",
            ["how to make", "recipe", "without drippings", "from drippings", "from scratch"],
        )
        if isinstance(noisy_phrases, str):
            noisy_phrases = [p.strip() for p in noisy_phrases.split(",") if p.strip()]
        candidate_names = []
        excluded = []
        for tag in tags:
            name = (tag.get("name") or "").strip()
            if not name:
                continue
            count = usage.get(name, 0)
            too_long = self.tag_max_name_length > 0 and len(name) > self.tag_max_name_length
            too_rare = self.tag_min_usage > 0 and count < self.tag_min_usage
            noisy_name = any(phrase in name.lower() for phrase in noisy_phrases)
            if too_long or too_rare or noisy_name:
                excluded.append((name, count))
                continue
            candidate_names.append(name)

        if excluded:
            preview = ", ".join(f"{name}({count})" for name, count in sorted(excluded)[:10])
            self.log(f"[info] Excluding {len(excluded)} low-quality tag candidates from prompting: {preview}")
            self.increment_stat("excluded_tag_candidates", len(excluded))

        return sorted(set(candidate_names))

    def select_targets(self, all_recipes):
        if self.replace_existing:
            return all_recipes
        if self.target_mode == "missing-categories":
            return [r for r in all_recipes if not (r.get("recipeCategory") or [])]
        if self.target_mode == "missing-tags":
            return [r for r in all_recipes if not (r.get("tags") or [])]
        if self.target_mode == "missing-tools":
            return [r for r in all_recipes if not (r.get("tools") or r.get("recipeTool") or [])]
        return [
            r
            for r in all_recipes
            if not (r.get("recipeCategory") or []) or not (r.get("tags") or []) or not (r.get("tools") or r.get("recipeTool") or [])
        ]

    def _ensure_field_for_entries(self, entries, recipes_by_slug, field, names, make_prompt_fn, alt_keys=()):
        """Fill in a missing field (tags or tools) by querying the AI with a focused prompt."""
        missing_slugs = []
        for entry in entries:
            slug = (entry.get("slug") or "").strip()
            if slug and slug in recipes_by_slug and not entry.get(field):
                missing_slugs.append(slug)

        if not missing_slugs:
            return

        deduped = []
        seen = set()
        for slug in missing_slugs:
            if slug not in seen:
                seen.add(slug)
                deduped.append(recipes_by_slug[slug])

        results = self.safe_query_with_retry(make_prompt_fn(deduped, names))
        if not isinstance(results, list):
            return

        result_map = {}
        for item in results:
            slug = (item.get("slug") or "").strip()
            values = item.get(field)
            for alt in alt_keys:
                if values is None:
                    values = item.get(alt)
            if slug and isinstance(values, list):
                result_map[slug] = values

        for entry in entries:
            slug = (entry.get("slug") or "").strip()
            if slug in result_map and not (entry.get(field) or []):
                entry[field] = result_map[slug]

    def ensure_tags_for_entries(self, entries, recipes_by_slug, tag_names):
        self._ensure_field_for_entries(entries, recipes_by_slug, "tags", tag_names, self.make_tag_prompt)

    def ensure_tools_for_entries(self, entries, recipes_by_slug, tool_names):
        self._ensure_field_for_entries(entries, recipes_by_slug, "tools", tool_names, self.make_tool_prompt, alt_keys=("tool",))

    @staticmethod
    def _existing_tools(recipe):
        return list(recipe.get("tools") or recipe.get("recipeTool") or [])

    @staticmethod
    def _tool_payload_key(recipe):
        if "recipeTool" in recipe and "tools" not in recipe:
            return "recipeTool"
        return "tools"

    def update_recipe_metadata(
        self,
        recipe,
        category_names,
        tag_names,
        tool_names,
        categories_by_name,
        tags_by_name,
        tools_by_name,
    ):
        recipe_slug = recipe["slug"]
        existing_categories = [] if self.replace_existing else list(recipe.get("recipeCategory") or [])
        existing_tags = [] if self.replace_existing else list(recipe.get("tags") or [])
        existing_tools = [] if self.replace_existing else self._existing_tools(recipe)

        cat_slugs = {c.get("slug") for c in existing_categories}
        tag_slugs = {t.get("slug") for t in existing_tags}
        tool_slugs = {t.get("slug") for t in existing_tools}
        updated_categories = list(existing_categories)
        updated_tags = list(existing_tags)
        updated_tools = list(existing_tools)

        def append_matches(names, lookup, existing_set, target_list):
            changed = False
            added_names = []
            for name in names or []:
                key = name.strip().lower()
                match = lookup.get(key)
                if not match:
                    continue
                slug = match.get("slug")
                if slug in existing_set:
                    continue
                target_list.append(
                    {
                        "id": match.get("id"),
                        "name": match.get("name"),
                        "slug": slug,
                        "groupId": match.get("groupId"),
                    }
                )
                existing_set.add(slug)
                changed = True
                added_names.append(match.get("name"))
            return changed, added_names

        cats_changed, cats_added = append_matches(category_names, categories_by_name, cat_slugs, updated_categories)
        tags_changed, tags_added = append_matches(tag_names, tags_by_name, tag_slugs, updated_tags)
        tools_changed, tools_added = append_matches(tool_names, tools_by_name, tool_slugs, updated_tools)

        if not cats_changed and not tags_changed and not tools_changed:
            self.increment_stat("recipes_no_change")
            return False

        payload = {}
        if cats_changed:
            payload["recipeCategory"] = updated_categories
        if tags_changed:
            payload["tags"] = updated_tags
        if tools_changed:
            payload[self._tool_payload_key(recipe)] = updated_tools

        summary_bits = []
        if cats_changed:
            summary_bits.append(f"cats={', '.join(cats_added or [c.get('name') for c in updated_categories])}")
        if tags_changed:
            summary_bits.append(f"tags={', '.join(tags_added or [t.get('name') for t in updated_tags])}")
        if tools_changed:
            summary_bits.append(f"tools={', '.join(tools_added or [t.get('name') for t in updated_tools])}")

        if self.dry_run:
            self.log(f"[plan] {recipe_slug} -> {'; '.join(summary_bits)}")
            self.increment_stat("recipes_planned")
            self.increment_stat("categories_added", len(cats_added))
            self.increment_stat("tags_added", len(tags_added))
            self.increment_stat("tools_added", len(tools_added))
            return True

        response = requests.patch(
            f"{self.mealie_url}/recipes/{recipe_slug}",
            headers=self.headers,
            json=payload,
            timeout=60,
        )
        if response.status_code == 403:
            self.log(
                f"[warn] PATCH '{recipe_slug}' returned 403 (Mealie slug-mismatch bug: "
                f"stored slug differs from name-derived slug; see mealie#4915)"
            )
            self.increment_stat("update_failures")
            return False
        if response.status_code != 200:
            self.log(f"[error] Update failed '{recipe_slug}': {response.status_code} {response.text}")
            self.increment_stat("update_failures")
            return False

        self.log(f"[recipe] {recipe_slug} -> {'; '.join(summary_bits)}")
        self.increment_stat("recipes_updated")
        self.increment_stat("categories_added", len(cats_added))
        self.increment_stat("tags_added", len(tags_added))
        self.increment_stat("tools_added", len(tools_added))

        with self.cache_lock:
            self.cache[recipe_slug] = {
                "categories": [c.get("name") for c in updated_categories],
                "tags": [t.get("name") for t in updated_tags],
                "tools": [t.get("name") for t in updated_tools],
            }
            self.save_cache()
        return True

    @staticmethod
    def batch_recipes(recipes, size):
        for i in range(0, len(recipes), size):
            yield recipes[i : i + size]

    @staticmethod
    def normalize_name_list(value):
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]
        if isinstance(value, list):
            normalized = []
            for item in value:
                text = str(item).strip()
                if text:
                    normalized.append(text)
            return normalized
        return []

    def extract_entry_for_slug(self, parsed, slug):
        if not isinstance(parsed, list):
            return None
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            if (entry.get("slug") or "").strip() == slug:
                return entry
        return None

    def parse_entry_labels(self, entry):
        categories = self.normalize_name_list(entry.get("categories"))
        tags_field = entry.get("tags")
        if tags_field is None:
            tags_field = entry.get("tag") or entry.get("labels")
        tags = self.normalize_name_list(tags_field)
        tools_field = entry.get("tools")
        if tools_field is None:
            tools_field = entry.get("tool")
        tools = self.normalize_name_list(tools_field)
        return categories, tags, tools

    def apply_parsed_entries_to_batch(
        self,
        batch,
        parsed,
        tag_names,
        tool_names,
        categories_by_name,
        tags_by_name,
        tools_by_name,
    ):
        recipes_by_slug = {r.get("slug"): r for r in batch if r.get("slug")}
        processed = set()
        self.ensure_tags_for_entries(parsed, recipes_by_slug, tag_names)
        self.ensure_tools_for_entries(parsed, recipes_by_slug, tool_names)

        for entry in parsed:
            if not isinstance(entry, dict):
                continue

            slug = (entry.get("slug") or "").strip()
            if not slug:
                continue
            recipe = recipes_by_slug.get(slug)
            if not recipe:
                self.log(f"[warn] Ignoring unknown slug from model: {slug}")
                self.increment_stat("unknown_slug_count")
                continue

            categories, tags, tools = self.parse_entry_labels(entry)
            self.update_recipe_metadata(recipe, categories, tags, tools, categories_by_name, tags_by_name, tools_by_name)
            processed.add(slug)

        missing = sorted(set(recipes_by_slug) - processed)
        if missing:
            self.log(f"[warn] Model returned no data for: {', '.join(missing)}")
            self.increment_stat("model_missing_entry_count", len(missing))

        return len(recipes_by_slug)

    def classify_single_recipe_with_fallback(self, recipe, category_names, tag_names, tool_names):
        slug = (recipe.get("slug") or "").strip()
        if not slug:
            return None

        parsed = self.safe_query_with_retry(self.make_prompt([recipe], category_names, tag_names, tool_names))
        entry = self.extract_entry_for_slug(parsed, slug)
        if entry:
            categories, tags, tools = self.parse_entry_labels(entry)
            return {"slug": slug, "categories": categories, "tags": tags, "tools": tools}

        self.log(f"[warn] Per-recipe classify failed for {slug}; trying split category/tag/tool prompts.")

        categories = []
        category_results = self.safe_query_with_retry(self.make_category_prompt([recipe], category_names))
        category_entry = self.extract_entry_for_slug(category_results, slug)
        if category_entry:
            categories = self.normalize_name_list(category_entry.get("categories"))

        tags = []
        tag_results = self.safe_query_with_retry(self.make_tag_prompt([recipe], tag_names))
        tag_entry = self.extract_entry_for_slug(tag_results, slug)
        if tag_entry:
            tags_field = tag_entry.get("tags")
            if tags_field is None:
                tags_field = tag_entry.get("tag") or tag_entry.get("labels")
            tags = self.normalize_name_list(tags_field)

        tools = []
        tool_results = self.safe_query_with_retry(self.make_tool_prompt([recipe], tool_names))
        tool_entry = self.extract_entry_for_slug(tool_results, slug)
        if tool_entry:
            tools_field = tool_entry.get("tools")
            if tools_field is None:
                tools_field = tool_entry.get("tool")
            tools = self.normalize_name_list(tools_field)

        if not categories and not tags and not tools:
            return None

        return {"slug": slug, "categories": categories, "tags": tags, "tools": tools}

    def process_batch_with_fallback(
        self,
        batch,
        category_names,
        tag_names,
        tool_names,
        categories_by_name,
        tags_by_name,
        tools_by_name,
    ):
        self.log("[warn] Falling back to per-recipe classification for this batch.")
        self.increment_stat("fallback_batches")
        for recipe in batch:
            slug = (recipe.get("slug") or "").strip() or "(missing slug)"
            self.increment_stat("per_recipe_fallback_attempts")
            entry = self.classify_single_recipe_with_fallback(recipe, category_names, tag_names, tool_names)
            if not entry:
                self.log(f"[warn] No classification returned for {slug} after fallback attempts.")
                self.increment_stat("per_recipe_no_classification")
                self.advance_progress(1)
                continue

            categories = self.normalize_name_list(entry.get("categories"))
            tags = self.normalize_name_list(entry.get("tags"))
            tools = self.normalize_name_list(entry.get("tools"))
            self.update_recipe_metadata(
                recipe,
                categories,
                tags,
                tools,
                categories_by_name,
                tags_by_name,
                tools_by_name,
            )
            self.advance_progress(1)

    def process_batch(self, batch, category_names, tag_names, tool_names, categories_by_name, tags_by_name, tools_by_name):
        if not batch:
            return

        if not self.replace_existing and not self.dry_run:
            cached_slugs = [
                r["slug"]
                for r in batch
                if r.get("slug") in self.cache
                and (r.get("recipeCategory") or [])
                and (r.get("tags") or [])
                and self._existing_tools(r)
            ]
            if cached_slugs:
                self.advance_progress(len(cached_slugs))
                self.increment_stat("cached_skipped", len(cached_slugs))
            batch = [
                r
                for r in batch
                if not (
                    r.get("slug") in self.cache
                    and (r.get("recipeCategory") or [])
                    and (r.get("tags") or [])
                    and self._existing_tools(r)
                )
            ]
            if not batch:
                return

        parsed = self.safe_query_with_retry(self.make_prompt(batch, category_names, tag_names, tool_names))
        if not isinstance(parsed, list):
            self.log("[warn] Batch failed parsing after retries.")
            self.increment_stat("batch_parse_failures")
            self.process_batch_with_fallback(
                batch,
                category_names,
                tag_names,
                tool_names,
                categories_by_name,
                tags_by_name,
                tools_by_name,
            )
            return

        processed_count = self.apply_parsed_entries_to_batch(
            batch,
            parsed,
            tag_names,
            tool_names,
            categories_by_name,
            tags_by_name,
            tools_by_name,
        )
        self.advance_progress(processed_count)

    def run(self):
        self.reset_stats()
        mode = (
            "RE-CATEGORIZATION (All Recipes)"
            if self.replace_existing
            else {
                "missing-categories": "Categorize Missing Categories",
                "missing-tags": "Tag Missing Tags",
                "missing-tools": "Assign Missing Tools",
                "missing-either": "Categorize/Tag/Tool Missing Categories Or Tags Or Tools",
            }.get(self.target_mode, "Categorize/Tag/Tool Missing Categories Or Tags Or Tools")
        )
        self.log(f"[start] Mode: {mode}")
        self.log(f"[start] Provider: {self.provider_name}")
        self.log(f"[start] Dry-run mode: {'ON' if self.dry_run else 'OFF'}")

        all_recipes = self.get_all_recipes()
        categories = self.get_all_categories()
        tags = self.get_all_tags()
        tools = self.get_all_tools()

        categories_by_name = {c.get("name", "").strip().lower(): c for c in categories if c.get("name")}
        tags_by_name = {t.get("name", "").strip().lower(): t for t in tags if t.get("name")}
        tools_by_name = {t.get("name", "").strip().lower(): t for t in tools if t.get("name")}
        category_names = sorted(name for name in {c.get("name", "").strip() for c in categories} if name)
        tag_names = self.filter_tag_candidates(tags, all_recipes)
        tool_names = sorted(name for name in {t.get("name", "").strip() for t in tools} if name)
        if not tag_names:
            tag_names = sorted(name for name in {t.get("name", "").strip() for t in tags} if name)
            self.log("[warn] Tag candidate filtering removed everything; using full tag list.")

        targets = self.select_targets(all_recipes)
        self.log(f"Found {len(targets)} recipes to process.")

        self.set_progress_total(len(targets))
        if not targets:
            self.log("[done] Categorization complete.")
            self.print_summary()
            return

        reporter = threading.Thread(target=self.eta_reporter, daemon=True)
        reporter.start()

        batches = list(self.batch_recipes(targets, self.batch_size))
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [
                executor.submit(
                    self.process_batch,
                    batch,
                    category_names,
                    tag_names,
                    tool_names,
                    categories_by_name,
                    tags_by_name,
                    tools_by_name,
                )
                for batch in batches
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    self.log(f"[error] Batch crashed: {exc}")
        self.progress_stop_event.set()
        reporter.join(timeout=1)
        done, total, start_time = self.progress_snapshot()
        self.log(self.render_progress_line(done, total, start_time))
        self.log("[done] Categorization complete.")
        self.print_summary()
