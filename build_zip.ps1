# Package astrbot_plugin_moe_star_whisper into an AstrBot-installable zip.
# Keep this file ASCII-only: PS 5.1 on a non-UTF8 code page can mis-parse
# UTF-8 no-BOM files that contain CJK comments.
#
# Layout: wrapped in a top-level "<plugin>/" folder (AstrBot accepts both
# layouts; this repo ships wrapped). Entries use forward slashes. Directory
# entries are written explicitly (Compress-Archive omits them and AstrBot
# then refuses the install).
# Guard: every top-level .py on disk MUST be in the include list, otherwise
# packaging fails loudly (never ship a silently-missing module).
# dist/ is git-ignored; zips are local install artifacts and are kept forever.
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\build_zip.ps1

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$pluginName = "astrbot_plugin_moe_star_whisper"
$root = $PSScriptRoot
$distDir = Join-Path $root "dist"
$metaPath = Join-Path $root "metadata.yaml"

if (-not (Test-Path $metaPath)) {
    Write-Host "ERROR: metadata.yaml not found" -ForegroundColor Red
    exit 1
}

# --- WebUI: rebuild pages/console from webui-src before packaging ---
# (keeps the shipped console in sync with the frontend sources; the built
#  directory IS tracked in git, so a stale build would silently ship)
if (Test-Path (Join-Path $root "webui-src/package.json")) {
    $webuiScript = Join-Path $root "build_webui.ps1"
    if (-not (Test-Path $webuiScript)) {
        Write-Host "ERROR: webui-src/ exists but build_webui.ps1 is missing" -ForegroundColor Red
        exit 1
    }
    Write-Host "==> building WebUI (pages/console)..." -ForegroundColor Cyan
    $buildStart = [DateTime]::UtcNow
    & powershell -NoProfile -ExecutionPolicy Bypass -File $webuiScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: WebUI build failed, aborting package" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path (Join-Path $root "pages/console/index.html"))) {
        Write-Host "ERROR: pages/console/index.html missing after WebUI build" -ForegroundColor Red
        exit 1
    }
    # A green exit code alone is not enough: if vite was skipped, the OLD
    # index.html + old js are still on disk and both checks above pass.
    # Require at least one asset rewritten AFTER this build started.
    $jsFiles = @(Get-ChildItem -LiteralPath (Join-Path $root "pages/console/assets") -Filter *.js -File -ErrorAction SilentlyContinue)
    if ($jsFiles.Count -eq 0) {
        Write-Host "ERROR: no js assets in pages/console/assets after build" -ForegroundColor Red
        exit 1
    }
    $fresh = @($jsFiles | Where-Object { $_.LastWriteTimeUtc -ge $buildStart.AddSeconds(-2) })
    if ($fresh.Count -eq 0) {
        Write-Host "ERROR: WebUI assets were not refreshed by this build (stale pages/console would be packaged)" -ForegroundColor Red
        exit 1
    }
}

# --- version from metadata.yaml (explicit UTF-8: the file has CJK comments) ---
$metaRaw = [System.IO.File]::ReadAllText($metaPath, [System.Text.Encoding]::UTF8)
$version = ""
if ($metaRaw -match '(?m)^\s*version:\s*v?([0-9][^\s#]*)') {
    $version = $Matches[1].Trim()
}
if (-not $version) {
    Write-Host "ERROR: cannot read version from metadata.yaml" -ForegroundColor Red
    exit 1
}

# --- include list: every top-level .py is guarded below; directories auto-add
#     their directory entries (see the zip section), so adding one is enough.
$includeList = @(
    "main.py",
    "fortune.py",
    "lexicon.py",
    "lunar.py",
    "store.py",
    "webui_api.py",
    "card.py",
    "pages",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "data/lexicon"
)

# --- guard: every top-level .py on disk must be listed ---
$topPy = @(Get-ChildItem -LiteralPath $root -Filter *.py -File | ForEach-Object { $_.Name })
$notListed = @($topPy | Where-Object { $includeList -notcontains $_ })
if ($notListed.Count -gt 0) {
    Write-Host ("ERROR: top-level module(s) missing from includeList: " + ($notListed -join ", ")) -ForegroundColor Red
    Write-Host "       Add them to the include list in this script before packaging." -ForegroundColor Red
    exit 1
}

# --- zip path: refuse to overwrite an existing version ---
if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir | Out-Null
}
$zipPath = Join-Path $distDir ("{0}_v{1}.zip" -f $pluginName, $version)
if (Test-Path $zipPath) {
    Write-Host "ERROR: $zipPath already exists. Bump 'version' in metadata.yaml and add a CHANGELOG entry before repacking." -ForegroundColor Red
    exit 1
}

function Add-FileToZip($zip, $fsPath, $entryName) {
    # ZipFileExtensions::CreateEntryFromFile is an extension method and is NOT
    # callable from PS 5.1 (MethodNotFound) - write the entry manually instead.
    $entry = $zip.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
    $src = [System.IO.File]::OpenRead($fsPath)
    $dst = $entry.Open()
    try { $src.CopyTo($dst) } finally { $src.Dispose(); $dst.Dispose() }
}

$prefix = "$pluginName/"
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
$entryCount = 0
try {
    # Explicit directory entries (AstrBot needs them). Derive them from
    # includeList + the real on-disk tree: a hand-written list goes stale as
    # soon as a new folder is added, and the missing entry can make AstrBot
    # refuse the install.
    $dirEntries = @{}
    $dirEntries["$pluginName/"] = $true
    foreach ($rel in $includeList) {
        $fsPath = Join-Path $root ($rel -replace '/', '\')
        if (Test-Path $fsPath -PathType Container) {
            $parts = $rel.Split('/')
            for ($i = 1; $i -le $parts.Count; $i++) {
                $dirEntries[$prefix + (($parts[0..($i - 1)]) -join '/') + "/"] = $true
            }
            Get-ChildItem -LiteralPath $fsPath -Recurse -Directory | ForEach-Object {
                $sub = $_.FullName.Substring($fsPath.Length + 1).Replace('\', '/')
                $dirEntries[$prefix + $rel + "/" + $sub + "/"] = $true
            }
        }
    }
    foreach ($d in ($dirEntries.Keys | Sort-Object)) {
        [void]$zip.CreateEntry($d)
        $entryCount++
    }
    foreach ($rel in $includeList) {
        $fsPath = Join-Path $root ($rel -replace '/', '\')
        if (-not (Test-Path $fsPath)) {
            Write-Host "ERROR: include item missing on disk: $rel" -ForegroundColor Red
            $zip.Dispose()
            Remove-Item $zipPath -Force
            exit 1
        }
        if (Test-Path $fsPath -PathType Container) {
            Get-ChildItem -LiteralPath $fsPath -Recurse -File | ForEach-Object {
                $relInside = $_.FullName.Substring($fsPath.Length + 1).Replace('\', '/')
                $entryName = $prefix + $rel + "/" + $relInside
                Add-FileToZip $zip $_.FullName $entryName
                $entryCount++
            }
        }
        else {
            Add-FileToZip $zip $fsPath ($prefix + $rel)
            $entryCount++
        }
    }
}
finally {
    $zip.Dispose()
}

$sizeKb = [math]::Round((Get-Item $zipPath).Length / 1KB, 1)
Write-Host "OK: $zipPath  (entries: $entryCount, size: ${sizeKb} KB)" -ForegroundColor Green
