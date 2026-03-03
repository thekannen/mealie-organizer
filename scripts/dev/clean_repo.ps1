[CmdletBinding()]
param(
  [switch]$IncludeDependencies,
  [switch]$IncludeRuntime,
  [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $repoRoot

try {
  Write-Host "CookDex repo cleanup"
  Write-Host "Root: $repoRoot"

  if ($DryRun) {
    Write-Host "Mode: dry-run (no files will be deleted)"
  }

  $targets = @(
    ".pytest_cache",
    ".pytest_tmp",
    ".pytest_tmp2",
    ".pytest_tmp_push",
    ".ruff_cache",
    ".mypy_cache",
    ".tmp",
    ".playwright-mcp",
    "build",
    "dist",
    "src/cookdex.egg-info",
    "web/dist",
    "web/.vite",
    "web/reports",
    "htmlcov"
  )

  if ($IncludeDependencies) {
    $targets += @(
      ".venv",
      "venv",
      "web/node_modules"
    )
  }

  if ($IncludeRuntime) {
    $targets += @(
      "cache",
      "logs",
      "reports",
      "data",
      "state.db"
    )
  }

  foreach ($base in @("src", "scripts", "tests")) {
    if (Test-Path -LiteralPath $base) {
      $targets += Get-ChildItem -Path $base -Recurse -Directory -Filter "__pycache__" -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $_.FullName
      }
    }
  }

  $targets += Get-ChildItem -Path . -File -Filter ".coverage*" -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $_.FullName
  }

  $targets += Get-ChildItem -Path . -File -Filter "qa-*.png" -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $_.FullName
  }

  $uniqueTargets = $targets |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Sort-Object -Unique

  if (-not $uniqueTargets) {
    Write-Host "Nothing to clean."
    exit 0
  }

  function Get-PathSizeBytes {
    param([string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) {
      $measure = Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
      if ($null -eq $measure) {
        return 0
      }
      if ($null -eq $measure.Sum) {
        return 0
      }
      return [long]$measure.Sum
    }

    return [long]$item.Length
  }

  [long]$totalBytes = 0
  [int]$removedCount = 0

  foreach ($target in $uniqueTargets) {
    [long]$sizeBytes = Get-PathSizeBytes -Path $target
    $totalBytes += $sizeBytes
    $sizeMb = [Math]::Round(($sizeBytes / 1MB), 2)

    if ($DryRun) {
      Write-Host "[dry-run] remove $target ($sizeMb MB)"
      continue
    }

    try {
      Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
      $removedCount += 1
      Write-Host "[removed] $target ($sizeMb MB)"
    } catch {
      Write-Warning "Failed to remove '$target': $($_.Exception.Message)"
    }
  }

  $totalMb = [Math]::Round(($totalBytes / 1MB), 2)
  if ($DryRun) {
    Write-Host "Dry-run complete. Would remove $($uniqueTargets.Count) paths (~$totalMb MB)."
  } else {
    Write-Host "Cleanup complete. Removed $removedCount paths (~$totalMb MB)."
  }
}
finally {
  Pop-Location
}
