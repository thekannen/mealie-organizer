from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter


def _short_text(value: str, max_len: int = 240) -> str:
    text = value.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


@dataclass
class MealieApiClient:
    base_url: str
    api_key: str
    timeout_seconds: int = 30
    retries: int = 3
    backoff_seconds: float = 0.4

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key.strip()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        adapter = HTTPAdapter(max_retries=self._build_retry_policy())
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _build_retry_policy(self) -> object:
        retry_count = max(self.retries, 0)
        if retry_count == 0:
            return 0

        # Import lazily to avoid hard IDE/type-checker dependency on urllib3 symbols.
        try:
            retry_mod = __import__("urllib3.util.retry", fromlist=["Retry"])
            retry_cls = getattr(retry_mod, "Retry", None)
            if retry_cls is not None:
                return retry_cls(
                    total=retry_count,
                    connect=retry_count,
                    read=retry_count,
                    backoff_factor=max(self.backoff_seconds, 0.0),
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}),
                    raise_on_status=False,
                )
        except Exception:
            pass

        # Fallback to requests' integer retry handling if urllib3 Retry class is unavailable.
        return retry_count

    @staticmethod
    def _resolve_next_url(current_url: str, next_link: Any) -> str | None:
        if not isinstance(next_link, str) or not next_link:
            return None
        if next_link.lower().startswith(("http://", "https://")):
            return next_link

        if next_link.startswith("/"):
            base = urlsplit(current_url)
            rel = urlsplit(next_link)
            path = rel.path
            # Mealie may return '/recipes?...' even when requests target '/api/recipes?...'.
            if base.path.startswith("/api/") and not path.startswith("/api/"):
                path = f"/api{path}"
            return urlunsplit((base.scheme, base.netloc, path, rel.query, rel.fragment))

        return urljoin(current_url, next_link)

    def _make_url(self, path_or_url: str) -> str:
        if path_or_url.lower().startswith(("http://", "https://")):
            return path_or_url
        if not path_or_url.startswith("/"):
            path_or_url = f"/{path_or_url}"
        return f"{self.base_url}{path_or_url}"

    def _request_raw(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: int | None = None,
    ) -> requests.Response:
        url = self._make_url(path_or_url)
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=timeout or self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise requests.HTTPError(f"{method} {url} failed: {exc}") from exc

        if response.status_code >= 400:
            details = _short_text(response.text)
            try:
                payload = response.json()
                details = _short_text(str(payload))
            except ValueError:
                pass
            raise requests.HTTPError(
                f"{method} {url} failed ({response.status_code}): {details}",
                response=response,
            )
        return response

    def request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: int | None = None,
    ) -> Any:
        response = self._request_raw(method, path_or_url, params=params, json=json, timeout=timeout)
        try:
            return response.json()
        except ValueError as exc:
            raise requests.HTTPError(f"{method} {response.url} returned non-JSON response") from exc

    def get_paginated(self, path_or_url: str, *, per_page: int = 1000, timeout: int | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url = self._make_url(path_or_url)

        if "perPage=" not in next_url and "per_page=" not in next_url:
            join_char = "&" if "?" in next_url else "?"
            next_url = f"{next_url}{join_char}perPage={per_page}"

        while next_url:
            data = self.request_json("GET", next_url, timeout=timeout)
            if isinstance(data, list):
                if all(isinstance(item, dict) for item in data):
                    return items + data
                return items
            if not isinstance(data, dict):
                return items

            page_items = data.get("items")
            if page_items is None:
                return items
            if not isinstance(page_items, list):
                return items

            items.extend(item for item in page_items if isinstance(item, dict))
            next_url = self._resolve_next_url(next_url, data.get("next"))

        return items

    def get_recipes(self, *, per_page: int = 1000) -> list[dict[str, Any]]:
        return self.get_paginated("/recipes", per_page=per_page, timeout=60)

    def get_recipe(self, slug: str) -> dict[str, Any]:
        data = self.request_json("GET", f"/recipes/{slug}", timeout=60)
        if not isinstance(data, dict):
            raise requests.HTTPError(f"GET /recipes/{slug} returned invalid payload type: {type(data).__name__}")
        return data

    def patch_recipe(self, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self.request_json("PATCH", f"/recipes/{slug}", json=payload, timeout=60)
        if isinstance(data, dict):
            return data
        return {}

    def parse_ingredients(self, ingredients: list[str], strategy: str) -> list[dict[str, Any]]:
        data = self.request_json(
            "POST",
            "/parser/ingredients",
            json={"strategy": strategy, "ingredients": ingredients},
            timeout=60,
        )
        if not isinstance(data, list):
            raise requests.HTTPError(f"Unexpected parser response type: {type(data).__name__}")
        return [item for item in data if isinstance(item, dict)]

    def patch_recipe_ingredients(self, slug: str, ingredients: list[dict[str, Any]]) -> dict[str, Any]:
        return self.patch_recipe(slug, {"recipeIngredient": ingredients})

    def get_organizer_items(self, endpoint: str, *, per_page: int = 1000) -> list[dict[str, Any]]:
        return self.get_paginated(f"/organizers/{endpoint}", per_page=per_page, timeout=60)

    def create_organizer_item(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self.request_json("POST", f"/organizers/{endpoint}", json=payload, timeout=60)
        if isinstance(data, dict):
            return data
        return {}

    def delete_organizer_item(self, endpoint: str, item_id: str) -> None:
        self._request_raw("DELETE", f"/organizers/{endpoint}/{item_id}", timeout=60)

    def list_foods(self, *, per_page: int = 1000) -> list[dict[str, Any]]:
        return self.get_paginated("/foods", per_page=per_page, timeout=60)

    def create_food(self, name: str, group_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name}
        if group_id:
            payload["groupId"] = group_id
        data = self.request_json("POST", "/foods", json=payload, timeout=60)
        if isinstance(data, dict):
            return data
        return {}

    def merge_food(self, source_id: str, target_id: str) -> dict[str, Any]:
        return self._merge_entity("/foods/merge", source_id, target_id)

    def list_units(self, *, per_page: int = 1000) -> list[dict[str, Any]]:
        return self.get_paginated("/units", per_page=per_page, timeout=60)

    def create_unit(self, name: str, abbreviation: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name}
        if abbreviation:
            payload["abbreviation"] = abbreviation
        data = self.request_json("POST", "/units", json=payload, timeout=60)
        if isinstance(data, dict):
            return data
        return {}

    def merge_unit(self, source_id: str, target_id: str) -> dict[str, Any]:
        return self._merge_entity("/units/merge", source_id, target_id)

    def list_labels(self, *, per_page: int = 1000) -> list[dict[str, Any]]:
        return self.get_paginated("/groups/labels", per_page=per_page, timeout=60)

    def create_label(self, name: str) -> dict[str, Any]:
        data = self.request_json("POST", "/groups/labels", json={"name": name}, timeout=60)
        if isinstance(data, dict):
            return data
        return {}

    def delete_label(self, label_id: str) -> None:
        self._request_raw("DELETE", f"/groups/labels/{label_id}", timeout=60)

    @staticmethod
    def _is_http_404(exc: Exception) -> bool:
        if not isinstance(exc, requests.HTTPError):
            return False
        response = getattr(exc, "response", None)
        return bool(response is not None and response.status_code == 404)

    def list_tools(self, *, per_page: int = 1000) -> list[dict[str, Any]]:
        try:
            return self.get_paginated("/tools", per_page=per_page, timeout=60)
        except requests.HTTPError as exc:
            if not self._is_http_404(exc):
                raise
        return self.get_paginated("/organizers/tools", per_page=per_page, timeout=60)

    def create_tool(self, name: str) -> dict[str, Any]:
        try:
            data = self.request_json("POST", "/tools", json={"name": name}, timeout=60)
            if isinstance(data, dict):
                return data
            return {}
        except requests.HTTPError as exc:
            if not self._is_http_404(exc):
                raise
        return self.create_organizer_item("tools", {"name": name})

    def merge_tool(self, source_id: str, target_id: str) -> dict[str, Any]:
        try:
            return self._merge_entity("/tools/merge", source_id, target_id)
        except requests.HTTPError as exc:
            if not self._is_http_404(exc):
                raise
        # Older Mealie versions expose tools under organizers without a merge route.
        raise requests.HTTPError(
            "Tool merge endpoint is unavailable on this Mealie server/version. "
            "Tools can be seeded, but duplicate merges are not supported."
        )

    def _merge_entity(self, route: str, source_id: str, target_id: str) -> dict[str, Any]:
        payload_candidates = [
            {"fromId": source_id, "toId": target_id},
            {"from": source_id, "to": target_id},
            {"sourceId": source_id, "targetId": target_id},
            {"fromFood": source_id, "toFood": target_id},
            {"fromUnit": source_id, "toUnit": target_id},
            {"fromTool": source_id, "toTool": target_id},
        ]
        last_exc: Exception | None = None
        for payload in payload_candidates:
            try:
                data = self.request_json("POST", route, json=payload, timeout=60)
                if isinstance(data, dict):
                    return data
                return {}
            except requests.HTTPError as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return {}
