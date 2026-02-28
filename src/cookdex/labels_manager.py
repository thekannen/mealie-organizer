from __future__ import annotations

import argparse
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url, resolve_repo_path, to_bool


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = " ".join(text.strip().casefold().split())
    return text


@dataclass
class LabelEntry:
    name: str
    color: str = "#959595"


def load_label_entries(file_path: Path) -> list[LabelEntry]:
    if not file_path.exists():
        raise FileNotFoundError(f"Labels file not found: {file_path}")
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Labels file must be a JSON array.")
    entries: list[LabelEntry] = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            color = "#959595"
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            color = str(item.get("color") or "#959595").strip()
        else:
            continue
        if name:
            entries.append(LabelEntry(name=name, color=color))
    if not entries:
        raise ValueError("Labels file contains no valid entries.")
    deduped: list[LabelEntry] = []
    seen: set[str] = set()
    for entry in entries:
        norm = normalize_name(entry.name)
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(entry)
    return deduped


def load_label_names(file_path: Path) -> list[str]:
    """Backward-compatible wrapper that returns just names."""
    return [entry.name for entry in load_label_entries(file_path)]


class LabelsSyncManager:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = False,
        apply: bool = False,
        replace: bool = False,
        file_path: Path | str = "configs/taxonomy/labels.json",
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.replace = replace
        self.file_path = Path(file_path)

    def run(self) -> dict[str, Any]:
        desired = load_label_entries(self.file_path)
        desired_names = [entry.name for entry in desired]
        existing = self.client.list_labels(per_page=1000)
        existing_by_norm = {
            normalize_name(str(item.get("name") or "")): item
            for item in existing
            if str(item.get("name") or "").strip()
        }

        executable = self.apply and not self.dry_run
        print(f"[start] Syncing {len(desired)} label(s) from {self.file_path}", flush=True)
        created = 0
        skipped = 0
        deleted = 0
        failed = 0
        actions: list[dict[str, Any]] = []

        for entry in desired:
            norm = normalize_name(entry.name)
            if norm in existing_by_norm:
                skipped += 1
                actions.append({"action": "skip", "name": entry.name, "reason": "exists"})
                print(f"[skip] Label unchanged: {entry.name}", flush=True)
                continue
            if executable:
                try:
                    created_item = self.client.create_label(entry.name, color=entry.color)
                    created += 1
                    existing_by_norm[norm] = created_item
                    actions.append({"action": "create", "name": entry.name, "status": "created"})
                    print(f"[ok] Created label: {entry.name}", flush=True)
                except Exception as exc:
                    failed += 1
                    actions.append({"action": "create", "name": entry.name, "status": "failed", "error": str(exc)})
                    print(f"[error] Create label failed '{entry.name}': {exc}", flush=True)
            else:
                actions.append({"action": "create", "name": entry.name, "status": "planned"})
                print(f"[plan] Create label: {entry.name}", flush=True)

        if self.replace:
            desired_norms = {normalize_name(name) for name in desired_names}
            for norm, item in existing_by_norm.items():
                if norm in desired_norms:
                    continue
                label_id = str(item.get("id") or "").strip()
                name = str(item.get("name") or "")
                if not label_id:
                    continue
                if executable:
                    try:
                        self.client.delete_label(label_id)
                        deleted += 1
                        actions.append({"action": "delete", "name": name, "status": "deleted"})
                        print(f"[ok] Deleted label: {name}", flush=True)
                    except Exception as exc:
                        failed += 1
                        actions.append({"action": "delete", "name": name, "status": "failed", "error": str(exc)})
                        print(f"[error] Delete label failed '{name}': {exc}", flush=True)
                else:
                    actions.append({"action": "delete", "name": name, "status": "planned"})
                    print(f"[plan] Delete label: {name}", flush=True)

        report = {
            "summary": {
                "desired": len(desired_names),
                "existing": len(existing),
                "created": created,
                "deleted": deleted,
                "skipped": skipped,
                "failed": failed,
                "mode": "apply" if executable else "audit",
                "replace": bool(self.replace),
            },
            "actions": actions,
            "source_file": str(self.file_path),
        }
        print(
            f"[done] labels created={created} deleted={deleted} skipped={skipped} failed={failed}",
            flush=True,
        )
        summary = {
            "Labels in Config": len(desired),
            "Labels in Mealie": len(existing),
            "Created": created,
            "Deleted": deleted,
            "Skipped": skipped,
            "Failed": failed,
        }
        print(f"[summary] {json.dumps(summary)}", flush=True)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mealie labels catalog sync.")
    parser.add_argument("--apply", action="store_true", help="Apply creates/deletes.")
    parser.add_argument("--replace", action="store_true", help="Delete labels not present in source file.")
    parser.add_argument(
        "--file",
        default=str(env_or_config("LABELS_FILE", "labels.file", "configs/taxonomy/labels.json")),
        help="Path to labels JSON file.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)
    manager = LabelsSyncManager(
        MealieApiClient(
            base_url=resolve_mealie_url(),
            api_key=resolve_mealie_api_key(required=True),
            timeout_seconds=60,
            retries=3,
            backoff_seconds=0.4,
        ),
        dry_run=dry_run,
        apply=bool(args.apply),
        replace=bool(args.replace),
        file_path=resolve_repo_path(args.file),
    )
    manager.run()


if __name__ == "__main__":
    main()
