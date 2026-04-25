from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_overview_page_omits_redundant_dashboard_chrome():
    app_source = (REPO_ROOT / "web" / "src" / "App.jsx").read_text(encoding="utf-8")
    constants_source = (REPO_ROOT / "web" / "src" / "constants.js").read_text(encoding="utf-8")
    overview_source = (
        REPO_ROOT / "web" / "src" / "pages" / "overview" / "OverviewPage.jsx"
    ).read_text(encoding="utf-8")

    assert 'activePage !== "overview"' in app_source
    assert "System Overview" not in constants_source
    assert '<p className="label">Tasks</p>' not in overview_source
    assert '<p className="label">Users</p>' not in overview_source


def test_about_privacy_names_all_ai_provider_choices():
    about_source = (REPO_ROOT / "web" / "src" / "pages" / "about" / "AboutPage.jsx").read_text(
        encoding="utf-8"
    )

    assert "OpenAI, Anthropic, or Ollama" in about_source


def test_tasks_activity_statuses_do_not_wrap_and_log_actions_scroll():
    tasks_source = (
        REPO_ROOT / "web" / "src" / "pages" / "tasks" / "TasksPage.jsx"
    ).read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "function selectRunForLogs" in tasks_source
    assert "logOutputRef.current?.scrollIntoView" in tasks_source
    assert "View logs for" in tasks_source

    status_rule = re.search(r"\.status-indicator\s*\{(?P<body>[^}]+)\}", styles_source)
    assert status_rule is not None
    assert "white-space: nowrap;" in status_rule.group("body")

    run_status_rule = re.search(r"\.run-status-cell\s*\{(?P<body>[^}]+)\}", styles_source)
    assert run_status_rule is not None
    assert "min-width:" in run_status_rule.group("body")
