from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from .api_client import MealieApiClient
from .config import env_or_config, resolve_mealie_api_key, resolve_mealie_url
from .ingredient_parser import parser_run_config, run_parser
from .plugin_runtime import ParserRunController

DEFAULT_BASE_PATH = "/mo-plugin"
DEFAULT_TOKEN_COOKIES = ("mealie.access_token", "access_token")

INJECTOR_JS_TEMPLATE = """(() => {
  const BASE_PATH = "__BASE_PATH__";
  const BUTTON_ID = "mo-plugin-nav-btn";
  const STYLE_ID = "mo-plugin-nav-style";

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .mo-plugin-nav-btn {
        display: inline-flex;
        align-items: center;
        height: 34px;
        margin-left: 10px;
        padding: 0 14px;
        border-radius: 17px;
        text-decoration: none;
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.35);
        background: rgba(255,255,255,0.08);
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.01em;
        transition: background 120ms ease, border-color 120ms ease;
      }
      .mo-plugin-nav-btn:hover {
        background: rgba(255,255,255,0.18);
        border-color: rgba(255,255,255,0.6);
      }
    `;
    document.head.appendChild(style);
  }

  function topToolbar() {
    const selectors = [
      ".v-app-bar .v-toolbar__content",
      "header .v-toolbar__content",
      ".v-app-bar",
    ];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node) {
        return node;
      }
    }
    return null;
  }

  function ensureButton() {
    if (document.getElementById(BUTTON_ID)) {
      return;
    }
    const toolbar = topToolbar();
    if (!toolbar) {
      return;
    }
    ensureStyle();
    const link = document.createElement("a");
    link.id = BUTTON_ID;
    link.href = `${BASE_PATH}/page`;
    link.textContent = "Organizer";
    link.className = "mo-plugin-nav-btn";
    toolbar.appendChild(link);
  }

  function boot() {
    ensureButton();
    const observer = new MutationObserver(() => ensureButton());
    observer.observe(document.body, { childList: true, subtree: true });
    setInterval(ensureButton, 2500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
"""

PAGE_CSS = """
:root {
  --mo-primary: #e58325;
  --mo-accent: #007a99;
  --mo-surface: #ffffff;
  --mo-bg: #f7f9fc;
  --mo-text: #17212f;
  --mo-muted: #5f7084;
  --mo-border: #d9e1ea;
  --mo-success: #2f8b57;
  --mo-error: #b6283d;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: "Open Sans", "Segoe UI", sans-serif;
  background: linear-gradient(180deg, #fff8ef 0%, var(--mo-bg) 260px, var(--mo-bg) 100%);
  color: var(--mo-text);
}

.mo-header {
  background: linear-gradient(90deg, var(--mo-primary), #cc6e1a);
  color: #fff;
  padding: 20px 28px;
  box-shadow: 0 8px 20px rgba(67, 41, 15, 0.2);
}

.mo-header h1 {
  margin: 0;
  font-size: 1.25rem;
  letter-spacing: 0.01em;
}

.mo-header p {
  margin: 6px 0 0 0;
  opacity: 0.92;
  font-size: 0.92rem;
}

.mo-shell {
  max-width: 980px;
  margin: 28px auto;
  padding: 0 16px 36px 16px;
}

.mo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.mo-card {
  background: var(--mo-surface);
  border: 1px solid var(--mo-border);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 4px 16px rgba(23, 33, 47, 0.04);
}

.mo-title {
  margin: 0 0 8px 0;
  font-size: 0.92rem;
  color: var(--mo-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.mo-value {
  margin: 0;
  font-size: 1.45rem;
  font-weight: 700;
}

.mo-actions {
  margin-top: 18px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.mo-btn {
  border: none;
  border-radius: 10px;
  padding: 11px 16px;
  font-weight: 700;
  cursor: pointer;
  font-size: 0.92rem;
  background: var(--mo-accent);
  color: #fff;
}

.mo-btn[disabled] {
  opacity: 0.6;
  cursor: not-allowed;
}

.mo-btn-secondary {
  background: #e8eef6;
  color: #1f2f44;
}

.mo-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--mo-border);
  padding: 6px 10px;
  font-size: 0.82rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.mo-badge.running {
  color: #854f11;
  background: #fff1df;
  border-color: #efd1a8;
}

.mo-badge.succeeded {
  color: var(--mo-success);
  background: #e9f9ef;
  border-color: #bde6cb;
}

.mo-badge.failed {
  color: var(--mo-error);
  background: #fdecef;
  border-color: #f2bdc7;
}

.mo-badge.idle {
  color: #44566d;
  background: #edf1f7;
}

.mo-note {
  margin-top: 10px;
  font-size: 0.88rem;
  color: var(--mo-muted);
}

.mo-error {
  margin-top: 10px;
  color: var(--mo-error);
  font-weight: 600;
}

.mo-footer {
  margin-top: 18px;
  color: var(--mo-muted);
  font-size: 0.84rem;
}
"""

PAGE_JS_TEMPLATE = """(() => {
  const BASE_PATH = "__BASE_PATH__";
  const API = `${BASE_PATH}/api/v1`;

  const refs = {
    status: document.getElementById("mo-status"),
    started: document.getElementById("mo-started"),
    finished: document.getElementById("mo-finished"),
    summaryParsed: document.getElementById("mo-summary-parsed"),
    summaryReview: document.getElementById("mo-summary-review"),
    summaryCandidates: document.getElementById("mo-summary-candidates"),
    runButton: document.getElementById("mo-run"),
    refreshButton: document.getElementById("mo-refresh"),
    note: document.getElementById("mo-note"),
    error: document.getElementById("mo-error")
  };

  function formatTime(value) {
    if (!value) return "N/A";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function clearMessages() {
    refs.note.textContent = "";
    refs.error.textContent = "";
  }

  function setStatus(status) {
    refs.status.textContent = status;
    refs.status.className = `mo-badge ${status}`;
  }

  function renderSnapshot(snapshot) {
    setStatus(snapshot.status || "idle");
    refs.started.textContent = formatTime(snapshot.started_at);
    refs.finished.textContent = formatTime(snapshot.finished_at);

    const summary = snapshot.summary || {};
    refs.summaryParsed.textContent = String(summary.parsed_successfully || 0);
    refs.summaryReview.textContent = String(summary.requires_review || 0);
    refs.summaryCandidates.textContent = String(summary.total_candidates || 0);

    refs.runButton.disabled = snapshot.status === "running";
    if (snapshot.status === "running") {
      refs.note.textContent = "Dry-run parser is in progress.";
      refs.error.textContent = "";
    } else if (snapshot.status === "failed") {
      refs.note.textContent = "";
      refs.error.textContent = snapshot.error || "Parser run failed.";
    } else if (snapshot.status === "succeeded") {
      refs.note.textContent = "Dry-run completed. Review reports before any write run.";
      refs.error.textContent = "";
    } else {
      refs.note.textContent = "No parser run is currently active.";
      refs.error.textContent = "";
    }
  }

  async function fetchStatus() {
    const response = await fetch(`${API}/parser/status`, { credentials: "same-origin" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || payload.error || `status request failed (${response.status})`);
    }
    renderSnapshot(payload);
  }

  async function startDryRun() {
    clearMessages();
    refs.runButton.disabled = true;
    try {
      const response = await fetch(`${API}/parser/runs`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const payload = await response.json();
      if (response.status === 409) {
        refs.note.textContent = "A parser run is already active.";
        await fetchStatus();
        return;
      }
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || `run request failed (${response.status})`);
      }
      refs.note.textContent = "Dry-run started.";
      renderSnapshot(payload);
    } catch (error) {
      refs.error.textContent = String(error);
      refs.runButton.disabled = false;
    }
  }

  refs.runButton.addEventListener("click", () => {
    startDryRun().catch((error) => {
      refs.error.textContent = String(error);
    });
  });
  refs.refreshButton.addEventListener("click", () => {
    fetchStatus().catch((error) => {
      refs.error.textContent = String(error);
    });
  });

  fetchStatus().catch((error) => {
    refs.error.textContent = String(error);
  });
  setInterval(() => {
    fetchStatus().catch((error) => {
      refs.error.textContent = String(error);
    });
  }, 5000);
})();
"""

PAGE_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Mealie Organizer Parser Companion</title>
    <link rel="stylesheet" href="__BASE_PATH__/static/page.css" />
  </head>
  <body>
    <header class="mo-header">
      <h1>Mealie Organizer Parser Companion</h1>
      <p>Admin-only parser controls for dry-run validation before write operations.</p>
    </header>

    <main class="mo-shell">
      <section class="mo-grid">
        <article class="mo-card">
          <h2 class="mo-title">Run Status</h2>
          <p class="mo-value"><span id="mo-status" class="mo-badge idle">idle</span></p>
        </article>
        <article class="mo-card">
          <h2 class="mo-title">Parsed Recipes</h2>
          <p class="mo-value" id="mo-summary-parsed">0</p>
        </article>
        <article class="mo-card">
          <h2 class="mo-title">Needs Review</h2>
          <p class="mo-value" id="mo-summary-review">0</p>
        </article>
        <article class="mo-card">
          <h2 class="mo-title">Candidates</h2>
          <p class="mo-value" id="mo-summary-candidates">0</p>
        </article>
      </section>

      <section class="mo-card" style="margin-top: 14px;">
        <h2 class="mo-title">Parser Action</h2>
        <div class="mo-actions">
          <button id="mo-run" class="mo-btn" type="button">Start Dry-Run Parse</button>
          <button id="mo-refresh" class="mo-btn mo-btn-secondary" type="button">Refresh</button>
        </div>
        <div class="mo-note" id="mo-note"></div>
        <div class="mo-error" id="mo-error"></div>
        <div class="mo-footer">
          Started: <strong id="mo-started">N/A</strong><br />
          Finished: <strong id="mo-finished">N/A</strong>
        </div>
      </section>
    </main>

    <script src="__BASE_PATH__/static/page.js"></script>
  </body>
</html>
"""


def _short_text(value: str, max_len: int = 320) -> str:
    text = value.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def ensure_api_base_url(mealie_url: str) -> str:
    split = urlsplit(mealie_url.strip())
    if not split.scheme or not split.netloc:
        raise ValueError(f"Invalid mealie URL: {mealie_url!r}")
    path = split.path.rstrip("/")
    if not path:
        path = "/api"
    elif not path.endswith("/api"):
        path = f"{path}/api"
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def token_from_auth_header(value: str | None) -> str:
    if not value:
        return ""
    prefix = "bearer "
    lowered = value.lower()
    if not lowered.startswith(prefix):
        return ""
    token = value[len(prefix) :].strip()
    return token


def token_from_cookie_header(value: str | None, cookie_names: tuple[str, ...]) -> str:
    if not value:
        return ""
    cookie = SimpleCookie()
    cookie.load(value)
    for name in cookie_names:
        morsel = cookie.get(name)
        if morsel is None:
            continue
        token = str(morsel.value).strip()
        if token:
            return token
    return ""


def fetch_mealie_user_profile(token: str, mealie_url: str, timeout_seconds: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    response = requests.get(
        f"{ensure_api_base_url(mealie_url)}/users/self",
        headers=headers,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        detail = _short_text(response.text)
        raise requests.HTTPError(
            f"GET /users/self failed ({response.status_code}): {detail}",
            response=response,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise requests.HTTPError(f"GET /users/self returned invalid payload type: {type(data).__name__}")
    return data


@dataclass(frozen=True)
class PluginServerConfig:
    host: str
    port: int
    base_path: str
    token_cookie_names: tuple[str, ...]
    auth_timeout_seconds: int

    @property
    def api_prefix(self) -> str:
        return f"{self.base_path}/api/v1"


def plugin_server_config() -> PluginServerConfig:
    host = str(env_or_config("PLUGIN_BIND_HOST", "plugin.bind_host", "0.0.0.0")).strip() or "0.0.0.0"
    port = int(env_or_config("PLUGIN_BIND_PORT", "plugin.bind_port", 9102, int))
    raw_base_path = str(env_or_config("PLUGIN_BASE_PATH", "plugin.base_path", DEFAULT_BASE_PATH)).strip() or DEFAULT_BASE_PATH
    base_path = raw_base_path if raw_base_path.startswith("/") else f"/{raw_base_path}"
    base_path = base_path.rstrip("/") or DEFAULT_BASE_PATH
    raw_cookies = str(
        env_or_config(
            "PLUGIN_TOKEN_COOKIES",
            "plugin.token_cookies",
            ",".join(DEFAULT_TOKEN_COOKIES),
        )
    )
    cookie_names = tuple(item.strip() for item in raw_cookies.split(",") if item.strip()) or DEFAULT_TOKEN_COOKIES
    auth_timeout_seconds = int(env_or_config("PLUGIN_AUTH_TIMEOUT_SECONDS", "plugin.auth_timeout_seconds", 15, int))
    return PluginServerConfig(
        host=host,
        port=port,
        base_path=base_path,
        token_cookie_names=cookie_names,
        auth_timeout_seconds=auth_timeout_seconds,
    )


class PluginHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], config: PluginServerConfig):
        super().__init__(server_address, PluginRequestHandler)
        self.config = config
        self.run_controller = ParserRunController()
        self.mealie_url = resolve_mealie_url()
        self.mealie_api_key = resolve_mealie_api_key(required=True)


class PluginRequestHandler(BaseHTTPRequestHandler):
    server: PluginHTTPServer

    def log_message(self, fmt: str, *args: object) -> None:
        message = fmt % args
        print(f"[plugin-server] {self.address_string()} {message}", flush=True)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        config = self.server.config

        if path == f"{config.api_prefix}/health":
            self._write_json(200, {"ok": True})
            return

        if path == f"{config.api_prefix}/parser/status":
            if not self._require_admin():
                return
            self._write_json(200, self.server.run_controller.snapshot())
            return

        if path == f"{config.base_path}/static/injector.js":
            self._write_text(200, "application/javascript; charset=utf-8", self._render_injector_js())
            return

        if path == f"{config.base_path}/static/page.css":
            self._write_text(200, "text/css; charset=utf-8", PAGE_CSS)
            return

        if path == f"{config.base_path}/static/page.js":
            self._write_text(200, "application/javascript; charset=utf-8", self._render_page_js())
            return

        if path == f"{config.base_path}/page" or path == f"{config.base_path}/page/":
            if not self._require_admin():
                return
            self._write_text(200, "text/html; charset=utf-8", self._render_page_html())
            return

        self._write_json(404, {"error": "not_found", "detail": f"Unknown path: {path}"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        config = self.server.config
        if path != f"{config.api_prefix}/parser/runs":
            self._write_json(404, {"error": "not_found", "detail": f"Unknown path: {path}"})
            return
        if not self._require_admin():
            return

        snapshot = self.server.run_controller.start_dry_run()
        if snapshot is None:
            self._write_json(
                409,
                {
                    "error": "run_in_progress",
                    "detail": "A parser run is already active.",
                    "snapshot": self.server.run_controller.snapshot(),
                },
            )
            return

        run_id = str(snapshot.get("run_id") or "")
        worker = Thread(target=self._execute_parser_run, args=(run_id,), daemon=True)
        worker.start()
        self._write_json(202, snapshot)

    def _execute_parser_run(self, run_id: str) -> None:
        try:
            config = replace(parser_run_config(), dry_run=True)
            client = MealieApiClient(
                base_url=resolve_mealie_url(),
                api_key=resolve_mealie_api_key(required=True),
                timeout_seconds=config.timeout_seconds,
                retries=config.request_retries,
                backoff_seconds=config.request_backoff_seconds,
            )
            summary = run_parser(client, config)
            self.server.run_controller.complete_success(asdict(summary))
            print(f"[plugin-server] run {run_id} completed successfully", flush=True)
        except Exception as exc:
            self.server.run_controller.complete_failure(_short_text(str(exc)))
            print(f"[plugin-server] run {run_id} failed: {_short_text(str(exc))}", flush=True)

    def _require_admin(self) -> bool:
        token = token_from_auth_header(self.headers.get("Authorization"))
        if not token:
            token = token_from_cookie_header(
                self.headers.get("Cookie"),
                self.server.config.token_cookie_names,
            )
        if not token:
            self._write_json(
                401,
                {
                    "error": "missing_token",
                    "detail": "Provide a bearer token or valid session cookie.",
                },
            )
            return False

        try:
            user = fetch_mealie_user_profile(
                token=token,
                mealie_url=self.server.mealie_url,
                timeout_seconds=self.server.config.auth_timeout_seconds,
            )
        except Exception as exc:
            self._write_json(
                502,
                {
                    "error": "mealie_auth_failed",
                    "detail": _short_text(str(exc)),
                },
            )
            return False

        if not bool(user.get("admin")):
            self._write_json(
                403,
                {"error": "admin_required", "detail": "This plugin endpoint requires an admin user."},
            )
            return False
        return True

    def _render_injector_js(self) -> str:
        return INJECTOR_JS_TEMPLATE.replace("__BASE_PATH__", self.server.config.base_path)

    def _render_page_js(self) -> str:
        return PAGE_JS_TEMPLATE.replace("__BASE_PATH__", self.server.config.base_path)

    def _render_page_html(self) -> str:
        return PAGE_HTML_TEMPLATE.replace("__BASE_PATH__", self.server.config.base_path)

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_text(self, status_code: int, content_type: str, body_text: str) -> None:
        body = body_text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    config = plugin_server_config()
    server = PluginHTTPServer((config.host, config.port), config)
    print(
        f"[start] plugin-server listening on http://{config.host}:{config.port}{config.base_path} "
        f"mealie={server.mealie_url}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[stop] plugin-server interrupted", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

