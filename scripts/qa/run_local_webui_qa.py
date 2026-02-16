from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
DEFAULT_BASE_PATH = "/cookdex"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, raw_value = text.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = raw_value.strip()
    return values


def run_command(command: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> int:
    final_command = list(command)
    if os.name == "nt":
        executable = final_command[0]
        if executable.lower() == "npm":
            npm_cmd = shutil.which("npm.cmd", path=(env or os.environ).get("PATH"))
            if npm_cmd:
                final_command[0] = npm_cmd
            else:
                final_command = ["cmd", "/c", *final_command]

    process = subprocess.run(final_command, cwd=REPO_ROOT, env=env, check=False)
    if check and process.returncode != 0:
        raise RuntimeError(f"Command failed ({process.returncode}): {' '.join(final_command)}")
    return process.returncode


def wait_for_health(url: str, timeout_seconds: int = 45) -> None:
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            response = requests.get(url, timeout=3)
            if response.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.8)
    raise RuntimeError(f"Server did not become healthy in time: {url}")


def ensure_playwright_ready(loop_env: dict[str, str]) -> None:
    run_command(["npm", "--prefix", "web", "install"], env=loop_env)
    run_command(["npm", "--prefix", "web", "exec", "playwright", "install", "chromium"], env=loop_env)


def build_server_env(
    *,
    dotenv_values: dict[str, str],
    admin_user: str,
    admin_password: str,
    port: int,
    base_path: str,
    state_db_path: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(dotenv_values)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["WEB_BIND_HOST"] = "127.0.0.1"
    env["WEB_BIND_PORT"] = str(port)
    env["WEB_BASE_PATH"] = base_path
    env["WEB_STATE_DB_PATH"] = str(state_db_path)
    env["WEB_BOOTSTRAP_USER"] = admin_user
    env["WEB_BOOTSTRAP_PASSWORD"] = admin_password
    env["MO_WEBUI_MASTER_KEY"] = env.get("MO_WEBUI_MASTER_KEY", "cookdex-local-qa-master-key")
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local CookDex build-test-analyze-debug loop with browser click-through verification."
    )
    parser.add_argument("--iterations", type=int, default=3, help="Maximum debug loop iterations.")
    parser.add_argument("--port", type=int, default=4920, help="Local web UI port.")
    parser.add_argument("--base-path", default=DEFAULT_BASE_PATH, help="Web UI base path.")
    parser.add_argument("--admin-user", default="qa-admin", help="Admin username used by smoke test.")
    parser.add_argument("--admin-password", default="qa-password-123", help="Admin password used by smoke test.")
    parser.add_argument(
        "--env-file",
        default=str(REPO_ROOT / ".env"),
        help="Path to .env file containing live credentials and environment values.",
    )
    parser.add_argument(
        "--skip-browser-install",
        action="store_true",
        help="Skip playwright npm install/browser installation step.",
    )
    args = parser.parse_args(argv)

    env_file = Path(args.env_file).resolve()
    dotenv_values = load_env_file(env_file)
    if not dotenv_values:
        raise RuntimeError(f"No environment values loaded from {env_file}")

    for required in ("MEALIE_URL", "MEALIE_API_KEY"):
        if not dotenv_values.get(required):
            raise RuntimeError(f"Missing required key in {env_file}: {required}")

    qa_root = REPO_ROOT / "reports" / "qa"
    qa_root.mkdir(parents=True, exist_ok=True)

    loop_env = os.environ.copy()
    if not args.skip_browser_install:
        print("[qa-loop] Ensuring playwright dependencies are installed...")
        ensure_playwright_ready(loop_env)

    expected_mealie_url = dotenv_values.get("MEALIE_URL", "").rstrip("/")
    base_url = f"http://127.0.0.1:{args.port}{args.base_path}"
    health_url = f"{base_url}/api/v1/health"

    for iteration in range(1, max(1, args.iterations) + 1):
        print(f"[qa-loop] Iteration {iteration}: build -> test -> analyze")
        iteration_dir = qa_root / f"loop-{iteration}"
        if iteration_dir.exists():
            shutil.rmtree(iteration_dir)
        iteration_dir.mkdir(parents=True, exist_ok=True)

        state_db_path = REPO_ROOT / ".tmp" / "qa" / f"state-loop-{iteration}.db"
        state_db_path.parent.mkdir(parents=True, exist_ok=True)
        if state_db_path.exists():
            state_db_path.unlink()

        server_env = build_server_env(
            dotenv_values=dotenv_values,
            admin_user=args.admin_user,
            admin_password=args.admin_password,
            port=args.port,
            base_path=args.base_path,
            state_db_path=state_db_path,
        )

        run_command(["npm", "--prefix", "web", "run", "build"], env=server_env)

        server_log = (iteration_dir / "server.log").open("w", encoding="utf-8")
        server_process: subprocess.Popen[str] | None = None
        try:
            server_process = subprocess.Popen(
                [sys.executable, "-m", "cookdex.webui_server.main"],
                cwd=REPO_ROOT,
                env=server_env,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wait_for_health(health_url)

            smoke_command = [
                "npm",
                "--prefix",
                "web",
                "run",
                "qa:smoke",
                "--",
                "--base-url",
                base_url,
                "--username",
                args.admin_user,
                "--password",
                args.admin_password,
                "--artifacts-dir",
                str(iteration_dir / "smoke"),
                "--expected-mealie-url",
                expected_mealie_url,
            ]

            code = run_command(smoke_command, env=server_env, check=False)
            if code == 0:
                print(f"[qa-loop] Iteration {iteration} passed.")
                return 0

            print(
                f"[qa-loop] Iteration {iteration} failed (smoke exit {code}). "
                f"See {iteration_dir / 'smoke' / 'report.json'} and {iteration_dir / 'server.log'}"
            )
        finally:
            if server_process is not None:
                server_process.terminate()
                try:
                    server_process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    server_process.kill()
            server_log.close()

    print("[qa-loop] All iterations failed. Review latest report and server log for debugging.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
