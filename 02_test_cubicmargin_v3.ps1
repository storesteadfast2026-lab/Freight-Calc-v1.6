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

    throw "Project root could not be detected automatically."
}

function Invoke-DockerChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$ReportFile
    )

    $startLine = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] START: $Description"
    Write-Host $startLine
    Add-Content -LiteralPath $ReportFile -Value $startLine -Encoding UTF8

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    $nativePreferenceExists = Test-Path variable:PSNativeCommandUseErrorActionPreference
    if ($nativePreferenceExists) {
        $previousNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        & docker @Arguments 2>&1 | Tee-Object -FilePath $ReportFile -Append
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
        $ErrorActionPreference = $previousPreference
    }

    if ($exitCode -ne 0) {
        $errorLine = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] FAILED: $Description (exit code $exitCode)"
        Write-Host $errorLine -ForegroundColor Red
        Add-Content -LiteralPath $ReportFile -Value $errorLine -Encoding UTF8
        throw "$Description failed with exit code $exitCode."
    }

    $okLine = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] OK: $Description"
    Write-Host $okLine -ForegroundColor Green
    Add-Content -LiteralPath $ReportFile -Value $okLine -Encoding UTF8
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or is not available in PATH."
}

$projectRoot = Find-ProjectRoot
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportDir = Join-Path $projectRoot "test_reports"
$reportFile = Join-Path $reportDir "cubicmargin_test_$timestamp.log"

New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

Push-Location $projectRoot
try {
    Add-Content -LiteralPath $reportFile -Value "Project: $projectRoot" -Encoding UTF8
    Add-Content -LiteralPath $reportFile -Value "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8

    Invoke-DockerChecked `
        -Description "Validate Docker Compose configuration" `
        -Arguments @("compose", "config", "--quiet") `
        -ReportFile $reportFile

    $services = & docker compose config --services
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read Docker Compose services."
    }

    $webService = $null
    foreach ($candidate in @("web", "app", "django")) {
        if ($services -contains $candidate) {
            $webService = $candidate
            break
        }
    }

    if (-not $webService) {
        $webService = $services | Select-Object -First 1
    }

    if (-not $webService) {
        throw "No Docker Compose service could be detected."
    }

    Write-Host "Docker service detected: $webService"

    $runningServices = & docker compose ps --status running --services
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read running Docker services."
    }

    if ($runningServices -notcontains $webService) {
        Invoke-DockerChecked `
            -Description "Build and start Docker service $webService" `
            -Arguments @("compose", "up", "-d", "--build", $webService) `
            -ReportFile $reportFile
    }

    Invoke-DockerChecked `
        -Description "Check Django version" `
        -Arguments @("compose", "exec", "-T", $webService, "python", "-m", "django", "--version") `
        -ReportFile $reportFile

    Invoke-DockerChecked `
        -Description "Run Django system checks" `
        -Arguments @("compose", "exec", "-T", $webService, "python", "/app/manage.py", "check") `
        -ReportFile $reportFile

    Invoke-DockerChecked `
        -Description "Check for pending model changes" `
        -Arguments @("compose", "exec", "-T", $webService, "python", "/app/manage.py", "makemigrations", "--check", "--dry-run") `
        -ReportFile $reportFile

    Invoke-DockerChecked `
        -Description "Run CubicMargin tests" `
        -Arguments @("compose", "exec", "-T", $webService, "python", "/app/manage.py", "test", "apps.freight.tests.test_cubic_margin", "-v", "2") `
        -ReportFile $reportFile

    Invoke-DockerChecked `
        -Description "Run freight application tests" `
        -Arguments @("compose", "exec", "-T", $webService, "python", "/app/manage.py", "test", "apps.freight.tests", "-v", "2") `
        -ReportFile $reportFile

    Write-Host ""
    Write-Host "ALL REQUESTED TESTS PASSED" -ForegroundColor Green
    Write-Host "Test report: $reportFile"
}
catch {
    $message = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] FINAL RESULT: FAILED - $($_.Exception.Message)"
    Add-Content -LiteralPath $reportFile -Value $message -Encoding UTF8

    Write-Host ""
    Write-Host "TEST EXECUTION FAILED" -ForegroundColor Red
    Write-Host "Review the report: $reportFile"
    exit 1
}
finally {
    Pop-Location
}
