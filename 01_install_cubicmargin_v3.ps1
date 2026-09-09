[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Find-ProjectRoot {
    $candidates = @(
        (Get-Location).Path,
        $PSScriptRoot,
        (Split-Path $PSScriptRoot -Parent)
    ) | Select-Object -Unique

    foreach ($candidate in $candidates) {
        if (
            (Test-Path -LiteralPath (Join-Path $candidate "app\manage.py")) -and
            (Test-Path -LiteralPath (Join-Path $candidate "docker-compose.yml"))
        ) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }

    foreach ($candidate in $candidates) {
        $found = Get-ChildItem -LiteralPath $candidate -Directory -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                (Test-Path -LiteralPath (Join-Path $_.FullName "app\manage.py")) -and
                (Test-Path -LiteralPath (Join-Path $_.FullName "docker-compose.yml"))
            } |
            Select-Object -First 1

        if ($found) {
            return [System.IO.Path]::GetFullPath($found.FullName)
        }
    }

    throw "Project root could not be detected automatically. Place this script in the project root or its parent folder."
}

function Find-UpdateZip {
    $searchRoots = @(
        (Join-Path $env:USERPROFILE "Downloads"),
        $PSScriptRoot,
        (Get-Location).Path,
        (Split-Path $PSScriptRoot -Parent)
    ) | Select-Object -Unique

    foreach ($root in $searchRoots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }

        $zip = Get-ChildItem -LiteralPath $root -File -Filter "*CubicMargin*0-20*.zip" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($zip) {
            return $zip.FullName
        }
    }

    throw "CubicMargin update ZIP could not be found. Place it in Downloads or next to this script."
}

$projectRoot = Find-ProjectRoot
$updateZip = Find-UpdateZip
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $projectRoot "file_backups\before_cubicmargin_$timestamp"
$extractDir = Join-Path $env:TEMP "cubicmargin_update_$timestamp"

$relativeFiles = @(
    "app\templates\freight\calculator.html",
    "app\apps\freight\services\calculator.py",
    "app\apps\freight\tests\test_cubic_margin.py"
)

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null

Write-Host "Project detected: $projectRoot"
Write-Host "Update package detected: $updateZip"
Write-Host ""

try {
    Write-Host "1/4 Backing up only files that will be replaced..."
    foreach ($relative in $relativeFiles) {
        $source = Join-Path $projectRoot $relative

        if (Test-Path -LiteralPath $source) {
            $destination = Join-Path $backupDir $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
            Copy-Item -LiteralPath $source -Destination $destination -Force
            Write-Host "Backed up: $relative"
        }
        else {
            Write-Host "Backup skipped because file does not exist: $relative"
        }
    }

    Write-Host ""
    Write-Host "2/4 Extracting update package..."
    Expand-Archive -LiteralPath $updateZip -DestinationPath $extractDir -Force

    foreach ($relative in $relativeFiles) {
        $packageFile = Join-Path $extractDir $relative
        if (-not (Test-Path -LiteralPath $packageFile)) {
            throw "Update package is missing required file: $relative"
        }
    }

    Write-Host "3/4 Installing CubicMargin files..."
    foreach ($relative in $relativeFiles) {
        $source = Join-Path $extractDir $relative
        $destination = Join-Path $projectRoot $relative

        New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
        Write-Host "Installed: $relative"
    }

    Write-Host ""
    Write-Host "4/4 Verifying installed files..."

    $templateFile = Join-Path $projectRoot "app\templates\freight\calculator.html"
    $calculatorFile = Join-Path $projectRoot "app\apps\freight\services\calculator.py"
    $testFile = Join-Path $projectRoot "app\apps\freight\tests\test_cubic_margin.py"

    $template = Get-Content -LiteralPath $templateFile -Raw
    $calculator = Get-Content -LiteralPath $calculatorFile -Raw
    $tests = Get-Content -LiteralPath $testFile -Raw

    if ($template -notmatch 'type\s*=\s*["'']number["'']') {
        throw "calculator.html does not contain the expected numeric input."
    }

    if ($template -notmatch 'min\s*=\s*["'']0["'']' -or $template -notmatch 'max\s*=\s*["'']20["'']') {
        throw "calculator.html does not contain the expected 0-20 range."
    }

    if ($calculator -notmatch "MAX_CUBIC_MARGIN_PERCENT\s*=\s*Decimal\(['""]20['""]\)") {
        throw "calculator.py does not contain MAX_CUBIC_MARGIN_PERCENT = Decimal('20')."
    }

    if ($tests -notmatch "apps\.freight\.services\.validators import ValidationError") {
        throw "test_cubic_margin.py does not contain the expected ValidationError import."
    }

    $manifest = @"
Timestamp: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Project: $projectRoot
Update package: $updateZip
Backup folder: $backupDir

Files backed up and replaced:
$($relativeFiles -join "`r`n")
"@
    Set-Content -LiteralPath (Join-Path $backupDir "INSTALL_MANIFEST.txt") -Value $manifest -Encoding UTF8

    Write-Host ""
    Write-Host "CUBICMARGIN UPDATE INSTALLED SUCCESSFULLY" -ForegroundColor Green
    Write-Host "File-level backup: $backupDir"
    Write-Host "Next step: run .\02_test_cubicmargin_v3.ps1"
}
finally {
    Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue
}
