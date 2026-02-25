from __future__ import annotations

from cookdex.tag_pipeline import build_parser


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.provider is None
    assert args.skip_ai is False
    assert args.skip_rules is False
    assert args.use_db is False
    assert args.missing_targets == "skip"
    assert args.config == ""


def test_parser_skip_ai_flag() -> None:
    args = build_parser().parse_args(["--skip-ai"])
    assert args.skip_ai is True


def test_parser_skip_rules_flag() -> None:
    args = build_parser().parse_args(["--skip-rules"])
    assert args.skip_rules is True


def test_parser_provider_override() -> None:
    args = build_parser().parse_args(["--provider", "anthropic"])
    assert args.provider == "anthropic"


def test_parser_use_db_flag() -> None:
    args = build_parser().parse_args(["--use-db"])
    assert args.use_db is True


def test_parser_missing_targets_create() -> None:
    args = build_parser().parse_args(["--missing-targets", "create"])
    assert args.missing_targets == "create"
