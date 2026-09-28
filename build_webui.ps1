# Build the Vue3 console (pages/console) for astrbot_plugin_moe_star_whisper.
#
# Steps:
#   1) inject the plugin version from metadata.yaml into webui-src/src/version.ts
#      (metadata.yaml is the single source of truth for the version)
#   2) npm install on first build (only when node_modules is missing)
#   3) vite build -> ../pages/console/
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\build_webui.ps1
#
# NOTE: keep this file ASCII-only. PS 5.1 on a non-UTF8 code page can mis-parse
#       UTF-8 no-BOM files that contain CJK comments.

$ErrorActionPreference = "Stop"

if ($PSScriptRoot) {
    $root = $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $root = (Get-Location).Path
}

$src = Join-Path $root "webui-src"
$out = Join-Path $root "pages/console"

Write-Host "==> Building console (pages/console)..." -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $src "package.json"))) {
    Write-Host "ERROR: $src\package.json not found" -ForegroundColor Red
    exit 1
}

Push-Location $src
try {
    # --- inject version from metadata.yaml (read as UTF8, file has CJK comments) ---
    $metaPath = Join-Path $root "metadata.yaml"
    $pluginVersion = "dev"
    if (Test-Path $metaPath) {
        $metaRaw = [System.IO.File]::ReadAllText($metaPath, [System.Text.Encoding]::UTF8)
        if ($metaRaw -match '(?m)^\s*version:\s*"?([^"#\r\n]+?)"?\s*(?:#.*)?$') {
            $pluginVersion = $Matches[1].Trim()
        }
    }
    $versionTs = "export const PLUGIN_VERSION = `"$pluginVersion`";`n"
    Set-Content -Path (Join-Path $src "src/version.ts") -Value $versionTs -Encoding UTF8
    Write-Host "==> injected plugin version: $pluginVersion" -ForegroundColor Green

    # --- dependencies on first build ---
    if (-not (Test-Path (Join-Path $src "node_modules"))) {
        Write-Host "==> node_modules missing, running npm install..." -ForegroundColor Yellow
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    }

    # --- build ---
    Write-Host "==> vite build..." -ForegroundColor Yellow
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "vite build failed" }
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $out "index.html"))) {
    Write-Host "ERROR: build finished but output is missing: $out\index.html" -ForegroundColor Red
    exit 1
}

$js = Get-ChildItem -LiteralPath (Join-Path $out "assets") -Filter *.js -ErrorAction SilentlyContinue
$sizeKb = if ($js) { [math]::Round(($js | Measure-Object -Property Length -Sum).Sum / 1KB, 1) } else { 0 }
Write-Host "==> done. output: $out  (js: ${sizeKb} KB)" -ForegroundColor Green
