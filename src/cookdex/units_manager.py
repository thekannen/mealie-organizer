from __future__ import annotations

import argparse
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_client import MealieApiClient
from .config import (
    env_or_config,
    resolve_mealie_api_key,
    resolve_mealie_url,
    resolve_repo_path,
    to_bool,
)


@dataclass
class UnitMergeAction:
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    reason: str


class UnitsCleanupManager:
    def __init__(
        self,
        client: MealieApiClient,
        *,
        dry_run: bool = False,
        apply: bool = False,
        max_actions: int = 250,
        alias_file: Path | str = "configs/taxonomy/units_aliases.json",
        report_file: Path | str = "reports/units_cleanup_report.json",
        checkpoint_dir: Path | str = "cache/maintenance",
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.apply = apply
        self.max_actions = max(1, int(max_actions))
        self.alias_file = Path(alias_file)
        self.report_file = Path(report_file)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_path = self.checkpoint_dir / "units_cleanup_checkpoint.json"

    @staticmethod
    def normalize_name(name: str) -> str:
        text = unicodedata.normalize("NFKC", str(name or ""))
        text = " ".join(text.strip().casefold().split())
        return text

    def load_aliases(self) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
        """Load unit entries and return (canonical_display, alias_to_canonical, unit_metadata).

        Supports both legacy format (``{canonical, aliases}``) and new Mealie-aligned
        format (``{name, pluralName, abbreviation, ...}``).  The ``name`` field is used
        as the canonical name when present; falls back to ``canonical``.
        """
        if not self.alias_file.exists():
            raise FileNotFoundError(f"Units alias file not found: {self.alias_file}")
        raw = json.loads(self.alias_file.read_text(encoding="utf-8"))
        canonical_display: dict[str, str] = {}
        alias_to_canonical: dict[str, str] = {}
        unit_metadata: dict[str, dict[str, Any]] = {}

        entries: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            for canonical, aliases in raw.items():
                entries.append({"canonical": canonical, "aliases": aliases})
        elif isinstance(raw, list):
            entries = [item for item in raw if isinstance(item, dict)]
        else:
            raise ValueError("Units alias file must be an object or array of objects.")

        for entry in entries:
            # Support both "name" (new) and "canonical" (legacy) as the primary key
            canonical = str(entry.get("name") or entry.get("canonical") or "").strip()
            if not canonical:
                raise ValueError("Each unit entry must include non-empty 'name' or 'canonical'.")
            canonical_norm = self.normalize_name(canonical)
            canonical_display.setdefault(canonical_norm, canonical)

            # Capture extended Mealie metadata for create_unit calls
            meta: dict[str, Any] = {}
            for field in ("pluralName", "abbreviation", "pluralAbbreviation", "description"):
                val = str(entry.get(field) or "").strip()
                if val:
                    meta[field] = val
            if "fraction" in entry:
                meta["fraction"] = bool(entry["fraction"])
            if "useAbbreviation" in entry:
                meta["useAbbreviation"] = bool(entry["useAbbreviation"])
            if meta:
                unit_metadata[canonical_norm] = meta

            aliases = entry.get("aliases") or []
            if not isinstance(aliases, list):
                raise ValueError(f"Aliases for '{canonical}' must be an array.")
            for alias in aliases:
                alias_name = str(alias or "").strip()
                if not alias_name:
                    continue
                alias_norm = self.normalize_name(alias_name)
                existing = alias_to_canonical.get(alias_norm)
                if existing and existing != canonical_norm:
                    raise ValueError(
                        f"Alias '{alias_name}' maps to multiple canonicals: "
                        f"'{canonical_display[existing]}' and '{canonical}'."
                    )
                alias_to_canonical[alias_norm] = canonical_norm
        return canonical_display, alias_to_canonical, unit_metadata

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

    def run(self) -> dict[str, Any]:
        canonical_display, alias_to_canonical, unit_metadata = self.load_aliases()
        units = self.client.list_units(per_page=1000)

        units_by_norm: dict[str, list[dict[str, Any]]] = {}
        for unit in units:
            unit_id = str(unit.get("id") or "").strip()
            name = str(unit.get("name") or "").strip()
            if not unit_id or not name:
                continue
            norm = self.normalize_name(name)
            if not norm:
                continue
            units_by_norm.setdefault(norm, []).append(unit)

        checkpoint = self.load_checkpoint()
        merged_source_ids = set(checkpoint)
        created_canonicals: list[dict[str, Any]] = []

        executable = self.apply and not self.dry_run
        canonical_id_by_norm: dict[str, str] = {}

        for canonical_norm, display in canonical_display.items():
            existing = units_by_norm.get(canonical_norm, [])
            if existing:
                canonical_id_by_norm[canonical_norm] = sorted(str(item.get("id")) for item in existing)[0]
                continue
            if executable:
                meta = unit_metadata.get(canonical_norm, {})
                created = self.client.create_unit(
                    display,
                    abbreviation=meta.get("abbreviation", ""),
                    plural_name=meta.get("pluralName", ""),
                    plural_abbreviation=meta.get("pluralAbbreviation", ""),
                    description=meta.get("description", ""),
                    fraction=meta.get("fraction", True),
                    use_abbreviation=meta.get("useAbbreviation", False),
                )
                created_id = str(created.get("id") or "").strip()
                if created_id:
                    canonical_id_by_norm[canonical_norm] = created_id
                    created_canonicals.append({"id": created_id, "name": display, "status": "created"})
            else:
                created_canonicals.append({"id": None, "name": display, "status": "planned_create"})

        for canonical_norm, items in units_by_norm.items():
            if canonical_norm in canonical_id_by_norm:
                continue
            canonical_id_by_norm[canonical_norm] = sorted(str(item.get("id")) for item in items)[0]

        actions: list[UnitMergeAction] = []

        # Exact duplicate names.
        for norm, items in units_by_norm.items():
            if len(items) <= 1:
                continue
            target_id = canonical_id_by_norm.get(norm)
            if not target_id:
                continue
            target_name = next((str(item.get("name") or "") for item in items if str(item.get("id")) == target_id), "")
            for item in items:
                source_id = str(item.get("id") or "")
                if source_id == target_id:
                    continue
                actions.append(
                    UnitMergeAction(
                        source_id=source_id,
                        source_name=str(item.get("name") or ""),
                        target_id=target_id,
                        target_name=target_name,
                        reason="exact_duplicate",
                    )
                )

        # Alias-driven merges.
        for norm, canonical_norm in alias_to_canonical.items():
            source_items = units_by_norm.get(norm, [])
            if not source_items:
                continue
            target_id = canonical_id_by_norm.get(canonical_norm)
            if not target_id:
                continue
            target_name = canonical_display.get(canonical_norm, "")
            for item in source_items:
                source_id = str(item.get("id") or "")
                if source_id == target_id:
                    continue
                actions.append(
                    UnitMergeAction(
                        source_id=source_id,
                        source_name=str(item.get("name") or ""),
                        target_id=target_id,
                        target_name=target_name or str(item.get("name") or ""),
                        reason="alias_map",
                    )
                )

        # Deduplicate actions by source, preferring alias_map.
        dedup: dict[str, UnitMergeAction] = {}
        for action in actions:
            existing = dedup.get(action.source_id)
            if not existing:
                dedup[action.source_id] = action
                continue
            if existing.reason != "alias_map" and action.reason == "alias_map":
                dedup[action.source_id] = action
        actions = sorted(dedup.values(), key=lambda action: (action.reason, action.source_name, action.source_id))

        unmapped_units = sorted(
            {
                str(item.get("name") or "")
                for norm, items in units_by_norm.items()
                if norm not in canonical_display and norm not in alias_to_canonical
                for item in items
                if str(item.get("name") or "").strip()
            }
        )

        attempted: list[dict[str, Any]] = []
        applied = 0
        failed = 0
        skipped_checkpoint = 0

        for action in actions:
            if action.source_id in checkpoint:
                skipped_checkpoint += 1
                continue
            if executable and applied >= self.max_actions:
                break

            entry = {
                "source_id": action.source_id,
                "source_name": action.source_name,
                "target_id": action.target_id,
                "target_name": action.target_name,
                "reason": action.reason,
                "mode": "apply" if executable else "plan",
            }
            if executable:
                try:
                    self.client.merge_unit(action.source_id, action.target_id)
                    applied += 1
                    merged_source_ids.add(action.source_id)
                    self.save_checkpoint(merged_source_ids)
                    entry["status"] = "merged"
                except Exception as exc:
                    failed += 1
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
            else:
                entry["status"] = "planned"
            attempted.append(entry)

        report = {
            "summary": {
                "units_total": len(units),
                "alias_entries": len(alias_to_canonical),
                "merge_candidates_total": len(actions),
                "actions_attempted": len(attempted),
                "actions_applied": applied,
                "actions_failed": failed,
                "checkpoint_skipped": skipped_checkpoint,
                "created_canonicals": len(created_canonicals),
                "unmapped_units": len(unmapped_units),
                "mode": "apply" if executable else "audit",
            },
            "created_canonicals": created_canonicals,
            "attempted_actions": attempted,
            "unmapped_units": unmapped_units,
            "checkpoint_file": str(self.checkpoint_path),
            "alias_file": str(self.alias_file),
        }

        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        s = report["summary"]
        print(
            f"[done] {s['merge_candidates_total']} merge candidate(s) — "
            f"{s['actions_applied']} applied ({s['mode']} mode)",
            flush=True,
        )
        print("[summary] " + json.dumps({
            "Units Total": s["units_total"],
            "Alias Entries": s["alias_entries"],
            "Merge Candidates": s["merge_candidates_total"],
            "Applied": s["actions_applied"],
            "Failed": s["actions_failed"],
            "Unmapped Units": s["unmapped_units"],
            "Mode": s["mode"],
        }), flush=True)
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
    parser = argparse.ArgumentParser(description="Mealie units standardization manager.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    cleanup = subparsers.add_parser("cleanup", help="Audit/apply units standardization actions.")
    cleanup.add_argument("--apply", action="store_true", help="Apply merge actions.")
    cleanup.add_argument(
        "--max-actions",
        type=int,
        default=require_int(
            env_or_config("MAX_ACTIONS_PER_STAGE", "maintenance.max_actions_per_stage", 250, int),
            "maintenance.max_actions_per_stage",
        ),
    )
    cleanup.add_argument(
        "--alias-file",
        default=str(env_or_config("UNITS_ALIAS_FILE", "units.alias_file", "configs/taxonomy/units_aliases.json")),
    )
    cleanup.add_argument(
        "--report-file",
        default=str(env_or_config("UNITS_REPORT_FILE", "units.report_file", "reports/units_cleanup_report.json")),
    )
    cleanup.add_argument(
        "--checkpoint-dir",
        default=str(env_or_config("CHECKPOINT_DIR", "maintenance.checkpoint_dir", "cache/maintenance")),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "cleanup":
        raise RuntimeError(f"Unsupported command: {args.command}")

    dry_run = bool(env_or_config("DRY_RUN", "runtime.dry_run", False, to_bool))
    if dry_run:
        print("[start] runtime.dry_run=true (writes disabled; planning only).", flush=True)

    client = MealieApiClient(
        base_url=resolve_mealie_url(),
        api_key=resolve_mealie_api_key(required=True),
        timeout_seconds=60,
        retries=3,
        backoff_seconds=0.4,
    )
    manager = UnitsCleanupManager(
        client,
        dry_run=dry_run,
        apply=bool(args.apply),
        max_actions=require_int(args.max_actions, "--max-actions"),
        alias_file=resolve_repo_path(args.alias_file),
        report_file=resolve_repo_path(args.report_file),
        checkpoint_dir=resolve_repo_path(args.checkpoint_dir),
    )
    manager.run()


if __name__ == "__main__":
    main()
