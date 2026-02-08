import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from .config import env_or_config


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
    cleaned = result_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("'", '"')
    cleaned = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    cleaned = re.sub(r"(\w+):", r'"\1":', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return None


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
        self.cache_lock = threading.Lock()
        self.cache = self.load_cache()

    def load_cache(self):
        if self.cache_file.exists():
            with self.cache_file.open("r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except Exception:
                    return {}
        return {}

    def save_cache(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def set_progress_total(self, total):
        with self.progress_lock:
            self.progress.update(total=total, done=0, start=time.time())

    def advance_progress(self, count):
        if not count:
            return
        with self.progress_lock:
            self.progress["done"] += count

    def progress_snapshot(self):
        with self.progress_lock:
            return self.progress["done"], self.progress["total"], self.progress["start"]

    def eta_reporter(self):
        while True:
            done, total, start_time = self.progress_snapshot()
            if done >= total:
                break
            elapsed = time.time() - start_time
            rate = done / elapsed if elapsed else 0
            remaining = (total - done) / rate if rate else 0
            eta_min = remaining / 60 if rate else float("inf")
            print(f"\r[progress] {done}/{total} ({rate:.2f}/s) ETA: {eta_min:.1f} min", end="")
            time.sleep(5)
        print()

    def get_all_recipes(self):
        response = requests.get(f"{self.mealie_url}/recipes?perPage=999", headers=self.headers, timeout=60)
        response.raise_for_status()
        return response.json().get("items", [])

    def get_all_categories(self):
        response = requests.get(f"{self.mealie_url}/organizers/categories", headers=self.headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("items", data)

    def get_all_tags(self):
        response = requests.get(f"{self.mealie_url}/organizers/tags", headers=self.headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("items", data)

    @staticmethod
    def make_prompt(recipes, category_names, tag_names):
        categories_text = "\n".join(f"- {name}" for name in category_names)
        tags_text = "\n".join(f"- {name}" for name in tag_names)
        prompt = f"""
You are a food recipe classifier.

For each recipe below:
1) Select one or more matching categories FROM THIS LIST ONLY.
2) Select one or more relevant tags FROM THIS LIST ONLY. Use an empty array ONLY if nothing fits.

Return results ONLY as valid JSON array like:
[
  {{"slug": "recipe-slug", "categories": ["Dinner"], "tags": ["Quick"]}}
]

If nothing matches, use empty arrays. Do not invent new names. No extra commentary.

Categories:
{categories_text}

Tags:
{tags_text}

Recipes:
"""
        for recipe in recipes:
            ingredients = ", ".join(i.get("title", "") for i in recipe.get("ingredients", [])[:10])
            prompt += (
                f"\n- slug={recipe.get('slug')} | name=\"{recipe.get('name', '')}\" | ingredients: {ingredients}"
            )
        return prompt.strip()

    @staticmethod
    def make_category_prompt(recipes, category_names):
        categories_text = "\n".join(f"- {name}" for name in category_names)
        prompt = f"""
You are a food recipe category selector.

Select one or more applicable categories for each recipe from THIS LIST ONLY:
{categories_text}

Return ONLY valid JSON array like:
[
  {{"slug": "recipe-slug", "categories": ["Dinner"]}}
]

If absolutely no categories match, use an empty array. No commentary.

Recipes:
"""
        for recipe in recipes:
            ingredients = ", ".join(i.get("title", "") for i in recipe.get("ingredients", [])[:10])
            prompt += (
                f"\n- slug={recipe.get('slug')} | name=\"{recipe.get('name', '')}\" | ingredients: {ingredients}"
            )
        return prompt.strip()

    @staticmethod
    def make_tag_prompt(recipes, tag_names):
        tags_text = "\n".join(f"- {name}" for name in tag_names)
        prompt = f"""
You are a food recipe tagging assistant.

Select at least one applicable tag for each recipe from THIS LIST ONLY:
{tags_text}

Return ONLY valid JSON array like:
[
  {{"slug": "recipe-slug", "tags": ["Quick", "Weeknight"]}}
]

If absolutely no tags match, use an empty array. No commentary.

Recipes:
"""
        for recipe in recipes:
            ingredients = ", ".join(i.get("title", "") for i in recipe.get("ingredients", [])[:10])
            prompt += (
                f"\n- slug={recipe.get('slug')} | name=\"{recipe.get('name', '')}\" | ingredients: {ingredients}"
            )
        return prompt.strip()

    def safe_query_with_retry(self, prompt_text, retries=None):
        attempts = retries if retries is not None else self.query_retries
        for attempt in range(attempts):
            result = self.query_text(prompt_text)
            if result:
                parsed = parse_json_response(result)
                if parsed:
                    return parsed
            print(f"[warn] Retry {attempt + 1}/{attempts} failed.")
            if attempt < attempts - 1:
                sleep_for = (self.query_retry_base_seconds * (2**attempt)) + random.uniform(0, 0.75)
                time.sleep(sleep_for)
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
        candidate_names = []
        excluded = []
        for tag in tags:
            name = (tag.get("name") or "").strip()
            if not name:
                continue
            count = usage.get(name, 0)
            too_long = self.tag_max_name_length > 0 and len(name) > self.tag_max_name_length
            too_rare = self.tag_min_usage > 0 and count < self.tag_min_usage
            noisy_name = any(
                phrase in name.lower()
                for phrase in ("how to make", "recipe", "without drippings", "from drippings", "from scratch")
            )
            if too_long or too_rare or noisy_name:
                excluded.append((name, count))
                continue
            candidate_names.append(name)

        if excluded:
            preview = ", ".join(f"{name}({count})" for name, count in sorted(excluded)[:10])
            print(f"[info] Excluding {len(excluded)} low-quality tag candidates from prompting: {preview}")

        return sorted(set(candidate_names))

    def select_targets(self, all_recipes):
        if self.replace_existing:
            return all_recipes
        if self.target_mode == "missing-categories":
            return [r for r in all_recipes if not (r.get("recipeCategory") or [])]
        if self.target_mode == "missing-tags":
            return [r for r in all_recipes if not (r.get("tags") or [])]
        return [
            r
            for r in all_recipes
            if not (r.get("recipeCategory") or []) or not (r.get("tags") or [])
        ]

    def ensure_tags_for_entries(self, entries, recipes_by_slug, tag_names):
        missing_slugs = []
        for entry in entries:
            slug = (entry.get("slug") or "").strip()
            if slug and slug in recipes_by_slug and not entry.get("tags"):
                missing_slugs.append(slug)

        if not missing_slugs:
            return

        deduped = []
        seen = set()
        for slug in missing_slugs:
            if slug not in seen:
                seen.add(slug)
                deduped.append(recipes_by_slug[slug])

        tag_results = self.safe_query_with_retry(self.make_tag_prompt(deduped, tag_names))
        if not isinstance(tag_results, list):
            return

        tag_map = {}
        for item in tag_results:
            slug = (item.get("slug") or "").strip()
            tags = item.get("tags") or []
            if slug and isinstance(tags, list):
                tag_map[slug] = tags

        for entry in entries:
            slug = (entry.get("slug") or "").strip()
            if slug in tag_map and not (entry.get("tags") or []):
                entry["tags"] = tag_map[slug]

    def update_recipe_metadata(self, recipe, category_names, tag_names, categories_by_name, tags_by_name):
        recipe_slug = recipe["slug"]
        existing_categories = [] if self.replace_existing else list(recipe.get("recipeCategory") or [])
        existing_tags = [] if self.replace_existing else list(recipe.get("tags") or [])

        cat_slugs = {c.get("slug") for c in existing_categories}
        tag_slugs = {t.get("slug") for t in existing_tags}
        updated_categories = list(existing_categories)
        updated_tags = list(existing_tags)

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

        if not cats_changed and not tags_changed:
            return False

        payload = {}
        if cats_changed:
            payload["recipeCategory"] = updated_categories
        if tags_changed:
            payload["tags"] = updated_tags

        summary_bits = []
        if cats_changed:
            summary_bits.append(f"cats={', '.join(cats_added or [c.get('name') for c in updated_categories])}")
        if tags_changed:
            summary_bits.append(f"tags={', '.join(tags_added or [t.get('name') for t in updated_tags])}")

        if self.dry_run:
            print(f"[plan] {recipe_slug} -> {'; '.join(summary_bits)}")
            return True

        response = requests.patch(
            f"{self.mealie_url}/recipes/{recipe_slug}",
            headers=self.headers,
            json=payload,
            timeout=60,
        )
        if response.status_code != 200:
            print(f"[error] Update failed '{recipe_slug}': {response.status_code} {response.text}")
            return False

        print(f"[recipe] {recipe_slug} -> {'; '.join(summary_bits)}")

        with self.cache_lock:
            self.cache[recipe_slug] = {
                "categories": [c.get("name") for c in updated_categories],
                "tags": [t.get("name") for t in updated_tags],
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
        return categories, tags

    def apply_parsed_entries_to_batch(self, batch, parsed, tag_names, categories_by_name, tags_by_name):
        recipes_by_slug = {r.get("slug"): r for r in batch if r.get("slug")}
        processed = set()
        self.ensure_tags_for_entries(parsed, recipes_by_slug, tag_names)

        for entry in parsed:
            if not isinstance(entry, dict):
                continue

            slug = (entry.get("slug") or "").strip()
            if not slug:
                continue
            recipe = recipes_by_slug.get(slug)
            if not recipe:
                print(f"[warn] Ignoring unknown slug from model: {slug}")
                continue

            categories, tags = self.parse_entry_labels(entry)
            self.update_recipe_metadata(recipe, categories, tags, categories_by_name, tags_by_name)
            processed.add(slug)

        missing = sorted(set(recipes_by_slug) - processed)
        if missing:
            print(f"[warn] Model returned no data for: {', '.join(missing)}")

        return len(recipes_by_slug)

    def classify_single_recipe_with_fallback(self, recipe, category_names, tag_names):
        slug = (recipe.get("slug") or "").strip()
        if not slug:
            return None

        parsed = self.safe_query_with_retry(self.make_prompt([recipe], category_names, tag_names))
        entry = self.extract_entry_for_slug(parsed, slug)
        if entry:
            categories, tags = self.parse_entry_labels(entry)
            return {"slug": slug, "categories": categories, "tags": tags}

        print(f"[warn] Per-recipe classify failed for {slug}; trying split category/tag prompts.")

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

        if not categories and not tags:
            return None

        return {"slug": slug, "categories": categories, "tags": tags}

    def process_batch_with_fallback(self, batch, category_names, tag_names, categories_by_name, tags_by_name):
        print("[warn] Falling back to per-recipe classification for this batch.")
        for recipe in batch:
            slug = (recipe.get("slug") or "").strip() or "(missing slug)"
            entry = self.classify_single_recipe_with_fallback(recipe, category_names, tag_names)
            if not entry:
                print(f"[warn] No classification returned for {slug} after fallback attempts.")
                self.advance_progress(1)
                continue

            categories = self.normalize_name_list(entry.get("categories"))
            tags = self.normalize_name_list(entry.get("tags"))
            self.update_recipe_metadata(recipe, categories, tags, categories_by_name, tags_by_name)
            self.advance_progress(1)

    def process_batch(self, batch, category_names, tag_names, categories_by_name, tags_by_name):
        if not batch:
            return

        if not self.replace_existing and not self.dry_run:
            cached_slugs = [r["slug"] for r in batch if r.get("slug") in self.cache]
            if cached_slugs:
                self.advance_progress(len(cached_slugs))
            batch = [r for r in batch if r.get("slug") not in self.cache]
            if not batch:
                return

        parsed = self.safe_query_with_retry(self.make_prompt(batch, category_names, tag_names))
        if not isinstance(parsed, list):
            print("[warn] Batch failed parsing after retries.")
            self.process_batch_with_fallback(batch, category_names, tag_names, categories_by_name, tags_by_name)
            return

        processed_count = self.apply_parsed_entries_to_batch(
            batch,
            parsed,
            tag_names,
            categories_by_name,
            tags_by_name,
        )
        self.advance_progress(processed_count)

    def run(self):
        mode = (
            "RE-CATEGORIZATION (All Recipes)"
            if self.replace_existing
            else {
                "missing-categories": "Categorize Missing Categories",
                "missing-tags": "Tag Missing Tags",
                "missing-either": "Categorize/Tag Missing Categories Or Tags",
            }.get(self.target_mode, "Categorize/Tag Missing Categories Or Tags")
        )
        print(f"[start] Mode: {mode}")
        print(f"[start] Provider: {self.provider_name}")
        print(f"[start] Dry-run mode: {'ON' if self.dry_run else 'OFF'}")

        all_recipes = self.get_all_recipes()
        categories = self.get_all_categories()
        tags = self.get_all_tags()

        categories_by_name = {c.get("name", "").strip().lower(): c for c in categories if c.get("name")}
        tags_by_name = {t.get("name", "").strip().lower(): t for t in tags if t.get("name")}
        category_names = sorted(name for name in {c.get("name", "").strip() for c in categories} if name)
        tag_names = self.filter_tag_candidates(tags, all_recipes)
        if not tag_names:
            tag_names = sorted(name for name in {t.get("name", "").strip() for t in tags} if name)
            print("[warn] Tag candidate filtering removed everything; using full tag list.")

        targets = self.select_targets(all_recipes)
        print(f"Found {len(targets)} recipes to process.")

        self.set_progress_total(len(targets))
        if not targets:
            return

        threading.Thread(target=self.eta_reporter, daemon=True).start()

        batches = list(self.batch_recipes(targets, self.batch_size))
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [
                executor.submit(
                    self.process_batch,
                    batch,
                    category_names,
                    tag_names,
                    categories_by_name,
                    tags_by_name,
                )
                for batch in batches
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"[error] Batch crashed: {exc}")

        print("\n[done] Categorization complete.")
