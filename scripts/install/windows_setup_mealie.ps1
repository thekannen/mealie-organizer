[CmdletBinding()]
param(
    [switch]$InstallOllama
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
Set-Location $repoRoot

Write-Host "[start] Checking Python"
$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    throw "Python launcher 'py' is required. Install Python 3.10+ from python.org and rerun."
}

if ($InstallOllama) {
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        Write-Host "[ok] Ollama already installed"
    }
    else {
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $wingetCmd) {
            throw "winget not found. Install Ollama manually from https://ollama.com/download/windows"
        }
        Write-Host "[start] Installing Ollama via winget"
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    }
}

Write-Host "[start] Creating virtual environment"
if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}

Write-Host "[start] Installing Python dependencies"
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install -e .

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "[ok] Created .env from .env.example"
}
else {
    Write-Host "[ok] Existing .env detected; leaving unchanged"
}

Write-Host "[done] Windows setup complete"
Write-Host "Next: edit .env, then run a categorizer script from repo root."
