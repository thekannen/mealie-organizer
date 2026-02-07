# Install Scripts

This folder contains cross-platform setup scripts for the Mealie Python tools in this repository.

## Ubuntu

Script: `scripts/install/ubuntu_setup_mealie.sh`

Run:

```bash
./scripts/install/ubuntu_setup_mealie.sh
```

Run directly on a server without cloning first:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | bash
```

Optional flags:
- `--target-dir <dir>`: where to clone/update the repo (default: `$HOME/mealie-scripts`).
- `--repo-url <url>`: override repository URL.
- `--repo-branch <branch>`: override repository branch.
- `--use-current-repo`: skip clone/update and use local repo path.
- `--update`: only update the repo and exit (no package/venv/cron setup).
- `--provider <ollama|chatgpt>`: choose one provider (default: `ollama`).
- `--install-ollama`: install Ollama if missing.
- `--skip-apt-update`: skip `apt-get update`.
- `--setup-cron`: install/update cron jobs.
- `--cron-schedule "<schedule>"`: cron schedule for selected provider.

What it does:
- Clones (or updates) the public repo into a target path
- Installs core packages (`python3`, `python3-venv`, `python3-pip`, `curl`)
- Creates `.venv` if missing
- Installs `requirements.txt`
- Installs package in editable mode (`pip install -e .`)
- Creates `.env` from `.env.example` if missing
- Optionally configures one cron job for the selected provider
- If a cron job exists for the other provider, it is removed

Update-only example:

```bash
./scripts/install/ubuntu_setup_mealie.sh --update --target-dir "$HOME/mealie-scripts"
```

Cron example:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | \
bash -s -- --provider ollama --install-ollama --setup-cron --cron-schedule "0 */6 * * *"
```

ChatGPT cron example:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | \
bash -s -- --provider chatgpt --setup-cron --cron-schedule "0 */6 * * *"
```

## Windows

Script: `scripts/install/windows_setup_mealie.ps1`

Run from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install\windows_setup_mealie.ps1
```

Optional flag:
- `-InstallOllama`: install Ollama via winget if missing.

What it does:
- Verifies `py` (Python launcher) is available
- Creates `.venv` if missing
- Installs `requirements.txt`
- Creates `.env` from `.env.example` if missing

## After install

1. Edit `.env` with your Mealie and provider credentials.
2. Run one categorizer script from repo root (choose one provider):

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py
```
