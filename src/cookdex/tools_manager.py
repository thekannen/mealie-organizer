from __future__ import annotations

import argparse
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .api_client import MealieApiClient
from .config import (
    env_or_config,
    resolve_mealie_api_key,
    resolve_mealie_url,
    resolve_repo_path,
    to_bool,
)


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = " ".join(text.strip().casefold().split())
    return text


@dataclass
class ToolEntry:
    name: str
    on_hand: bool = False


def load_tool_entries(file_path: Path) -> list[ToolEntry]:
    if not file_path.exists():
        raise FileNotFoundError(f"Tools file not found: {file_path}")
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Tools file must be a JSON array.")
    entries: list[ToolEntry] = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            on_hand = False
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            on_hand = bool(item.get("onHand", False))
        else:
            continue
        if name:
            entries.append(ToolEntry(name=name, on_hand=on_hand))
    if not entries:
        raise ValueError("Tools file contains no valid entries.")
    deduped: list[ToolEntry] = []
    seen: set[str] = set()
    for entry in entries:
        norm = normalize_name(entry.name)
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(entry)
    return deduped


def load_tool_names(file_path: Path) -> list[str]:
    """Backward-compatible wrapper that returns just names."""
    return [entry.name for entry in load_tool_entries(file_path)]


@dataclass
class ToolMergeAction:
    source_id: str
    source_name: str
    target_id: str
    target_name: str


class ToolsSyncManager:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = False,
        apply: bool = False,
        max_actions: int = 250,
        file_path: Path | str = "configs/taxonomy/tools.json",
        checkpoint_dir: Path | str = "cache/maintenance",
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.max_actions = max(1, int(max_actions))
        self.file_path = Path(file_path)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_path = self.checkpoint_dir / "tools_sync_checkpoint.json"

    def load_checkpoint(self) -> set[str]:
        if not self.checkpoint_path.exists():
            return set()
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        merged = payload.get("merged_source_ids", [])
        if not isinstance(merged, list):
            return set()
        return {str(item) for item in merged if str(item).strip()}

    def save_checkpoint(self, merged_source_ids: set[str]) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(
            json.dumps({"merged_source_ids": sorted(merged_source_ids)}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _http_status_code(exc: Exception) -> int | None:
        if not isinstance(exc, requests.HTTPError):
            return None
        response = getattr(exc, "response", None)
        if response is None:
            return None
        return response.status_code

    @classmethod
    def _is_endpoint_unavailable(cls, exc: Exception) -> bool:
        status_code = cls._http_status_code(exc)
        if status_code in {404, 405, 501}:
            return True
        return "endpoint is unavailable" in str(exc).lower()

    def build_duplicate_actions(self, tools: list[dict[str, Any]]) -> list[ToolMergeAction]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in tools:
            tool_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not tool_id or not name:
                continue
            groups.setdefault(normalize_name(name), []).append(item)
        actions: list[ToolMergeAction] = []
        for _, items in groups.items():
            if len(items) <= 1:
                continue
            target = sorted(items, key=lambda item: str(item.get("id") or ""))[0]
            target_id = str(target.get("id") or "")
            target_name = str(target.get("name") or "")
            for item in items:
                source_id = str(item.get("id") or "")
                if source_id == target_id:
                    continue
                actions.append(
                    ToolMergeAction(
                        source_id=source_id,
                        source_name=str(item.get("name") or ""),
                        target_id=target_id,
                        target_name=target_name,
                    )
                )
        return sorted(actions, key=lambda action: (action.source_name, action.source_id))

    def run(self) -> dict[str, Any]:
        desired = load_tool_names(self.file_path)
        print(f"[start] Syncing {len(desired)} tool(s) from {self.file_path}", flush=True)
        try:
            existing = self.client.list_tools(per_page=1000)
        except Exception as exc:
            report = {
                "summary": {
                    "desired": len(desired),
                    "existing": 0,
                    "created": 0,
                    "skipped": 0,
                    "merge_candidates_total": 0,
                    "merge_actions_attempted": 0,
                    "merged": 0,
                    "failed": 1,
                    "checkpoint_skipped": 0,
                    "mode": "apply" if (self.apply and not self.dry_run) else "audit",
                },
                "create_actions": [],
                "merge_actions": [],
                "source_file": str(self.file_path),
                "checkpoint_file": str(self.checkpoint_path),
                "error": str(exc),
            }
            print(f"[error] Failed to list tools: {exc}", flush=True)
            print("[hint] This Mealie server may not expose tools endpoints for this API version.", flush=True)
            return report
        existing_by_norm = {
            normalize_name(str(item.get("name") or "")): item
            for item in existing
            if str(item.get("name") or "").strip()
        }
        print(f"[start] Existing tools found: {len(existing)}", flush=True)

        executable = self.apply and not self.dry_run
        created = 0
        skipped = 0
        failed = 0
        create_actions: list[dict[str, Any]] = []
        endpoint_unavailable = False

        for index, name in enumerate(desired):
            norm = normalize_name(name)
            if norm in existing_by_norm:
                skipped += 1
                create_actions.append({"action": "skip", "name": name, "reason": "exists"})
                print(f"[skip] Tool unchanged: {name}", flush=True)
                continue
            if executable:
                try:
                    created_item = self.client.create_tool(name)
                    created += 1
                    existing_by_norm[norm] = created_item
                    create_actions.append({"action": "create", "name": name, "status": "created"})
                    print(f"[ok] Created tool: {name}", flush=True)
                except Exception as exc:
                    failed += 1
                    create_actions.append({"action": "create", "name": name, "status": "failed", "error": str(exc)})
                    print(f"[error] Create tool failed '{name}': {exc}", flush=True)
                    if self._is_endpoint_unavailable(exc):
                        endpoint_unavailable = True
                        remaining = desired[index + 1 :]
                        if remaining:
                            skipped += len(remaining)
                            for pending in remaining:
                                create_actions.append(
                                    {
                                        "action": "create",
                                        "name": pending,
                                        "status": "skipped",
                                        "reason": "endpoint_unavailable",
                                    }
                                )
                        print(
                            "[hint] Tool create endpoint is unavailable on this Mealie server/version; "
                            "skipping remaining create actions.",
                            flush=True,
                        )
                        break
            else:
                create_actions.append({"action": "create", "name": name, "status": "planned"})
                print(f"[plan] Create tool: {name}", flush=True)

        if endpoint_unavailable:
            merge_candidates: list[ToolMergeAction] = []
        else:
            try:
                tools = self.client.list_tools(per_page=1000)
                merge_candidates = self.build_duplicate_actions(tools)
            except Exception as exc:
                failed += 1
                merge_candidates = []
                print(f"[error] Failed to refresh tools for duplicate scan: {exc}", flush=True)
        checkpoint = self.load_checkpoint()
        merged_source_ids = set(checkpoint)
        merge_actions: list[dict[str, Any]] = []
        merged = 0
        skipped_checkpoint = 0

        for candidate in merge_candidates:
            if candidate.source_id in checkpoint:
                skipped_checkpoint += 1
                continue
            if executable and merged >= self.max_actions:
                break

            entry = {
                "source_id": candidate.source_id,
                "source_name": candidate.source_name,
                "target_id": candidate.target_id,
                "target_name": candidate.target_name,
                "mode": "apply" if executable else "plan",
            }
            if executable:
                try:
                    self.client.merge_tool(candidate.source_id, candidate.target_id)
                    merged += 1
                    merged_source_ids.add(candidate.source_id)
                    self.save_checkpoint(merged_source_ids)
                    entry["status"] = "merged"
                    print(
                        f"[ok] Merged duplicate tool '{candidate.source_name}' into '{candidate.target_name}'",
                        flush=True,
                    )
                except Exception as exc:
                    failed += 1
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
                    print(
                        f"[error] Merge tool failed '{candidate.source_name}' -> '{candidate.target_name}': {exc}",
                        flush=True,
                    )
                    if self._is_endpoint_unavailable(exc):
                        endpoint_unavailable = True
                        print(
                            "[hint] Tool merge endpoint is unavailable on this Mealie server/version; "
                            "skipping remaining merge actions.",
                            flush=True,
                        )
                        merge_actions.append(entry)
                        break
            else:
                entry["status"] = "planned"
                print(
                    f"[plan] Merge duplicate tool '{candidate.source_name}' into '{candidate.target_name}'",
                    flush=True,
                )
            merge_actions.append(entry)

        report = {
            "summary": {
                "desired": len(desired),
                "existing": len(existing),
                "created": created,
                "skipped": skipped,
                "merge_candidates_total": len(merge_candidates),
                "merge_actions_attempted": len(merge_actions),
                "merged": merged,
                "failed": failed,
                "checkpoint_skipped": skipped_checkpoint,
                "mode": "apply" if executable else "audit",
            },
            "create_actions": create_actions,
            "merge_actions": merge_actions,
            "source_file": str(self.file_path),
            "checkpoint_file": str(self.checkpoint_path),
        }
        print(
            "[done] "
            f"tools desired={len(desired)} existing={len(existing)} "
            f"created={created} skipped={skipped} merge_candidates={len(merge_candidates)} "
            f"merged={merged} failed={failed}",
            flush=True,
        )
        return report


def require_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            return int(text)
    raise ValueError(f"Invalid value for '{field}': expected integer-like, got {type(value).__name__}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mealie tools catalog sync and cleanup.")
    parser.add_argument("--apply", action="store_true", help="Apply creates/merges.")
    parser.add_argument(
        "--max-actions",
        type=int,
        default=require_int(
            env_or_config("MAX_ACTIONS_PER_STAGE", "maintenance.max_actions_per_stage", 250, int),
            "maintenance.max_actions_per_stage",
        ),
    )
    parser.add_argument(
        "--file",
        default=str(env_or_config("TOOLS_FILE", "tools.file", "configs/taxonomy/tools.json")),
        help="Path to tools JSON file.",
    )
    parser.add_argument(
        "--checkpoint-dir",
        default=str(env_or_config("CHECKPOINT_DIR", "maintenance.checkpoint_dir", "cache/maintenance")),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)
    manager = ToolsSyncManager(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=60,
            retries=3,
            backoff_seconds=0.4,
        ),
        dry_run=dry_run,
        apply=bool(args.apply),
        max_actions=require_int(args.max_actions, "--max-actions"),
        file_path=resolve_repo_path(args.file),
        checkpoint_dir=resolve_repo_path(args.checkpoint_dir),
    )
    manager.run()


if __name__ == "__main__":
    main()
