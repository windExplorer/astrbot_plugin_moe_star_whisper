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
        if ($metaRaw -match '(?m)^\s*version:\s*v?([0-9][^#\r\n\s]*)\s*(?:#.*)?$') {
            $pluginVersion = $Matches[1].Trim()
        }
    }
    # Strip a leading "v" so this matches webui_api._plugin_version() (which also
    # strips it). App.vue renders "v{{ version }}", so keeping the v here produced
    # "vv1.11.9" whenever the backend handshake failed.
    $pluginVersion = $pluginVersion -replace '^v', ''
    $versionTs = "export const PLUGIN_VERSION = `"$pluginVersion`";`n"
    Set-Content -Path (Join-Path $src "src/version.ts") -Value $versionTs -Encoding UTF8
    Write-Host "==> injected plugin version: $pluginVersion" -ForegroundColor Green

    # --- dependencies: reinstall when manifests changed, not only when the folder
    #     is missing. Editing package.json / package-lock.json used to silently
    #     rebuild pages/console with the OLD node_modules, shipping a new version
    #     number on top of stale frontend dependencies.
    $stampPath = Join-Path $src "node_modules/.deps-stamp"
    function Get-ManifestHash {
        $hash = ""
        foreach ($name in @("package.json", "package-lock.json")) {
            $p = Join-Path $src $name
            if (Test-Path $p) {
                $hash += (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
            }
        }
        return $hash
    }
    $manifestHash = Get-ManifestHash
    $needInstall = -not (Test-Path (Join-Path $src "node_modules"))
    if (-not $needInstall) {
        if (-not (Test-Path $stampPath)) {
            $needInstall = $true
        } elseif ([System.IO.File]::ReadAllText($stampPath).Trim() -ne $manifestHash) {
            $needInstall = $true
        }
    }
    if ($needInstall) {
        Write-Host "==> dependencies changed/missing, running npm install..." -ForegroundColor Yellow
        npm install
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: npm install failed" -ForegroundColor Red
            exit 1
        }
        # npm install may rewrite package-lock.json; stamp the FINAL manifests.
        $manifestHash = Get-ManifestHash
        [System.IO.File]::WriteAllText($stampPath, $manifestHash)
    }

    # --- build ---
    Write-Host "==> vite build..." -ForegroundColor Yellow
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: vite build failed" -ForegroundColor Red
        exit 1
    }
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
