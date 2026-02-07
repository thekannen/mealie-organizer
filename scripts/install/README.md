# Install Scripts

This folder contains cross-platform setup scripts for the Mealie Python tools in this repository.

## Ubuntu

Script: `scripts/install/ubuntu_setup_mealie.sh`

Run:

```bash
./scripts/install/ubuntu_setup_mealie.sh
```

Optional flags:
- `--install-ollama`: install Ollama if missing.
- `--skip-apt-update`: skip `apt-get update`.

What it does:
- Installs core packages (`python3`, `python3-venv`, `python3-pip`, `curl`)
- Creates `.venv` if missing
- Installs `requirements.txt`
- Creates `.env` from `.env.example` if missing

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
2. Run one of the categorizer scripts from repo root:

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py
```
