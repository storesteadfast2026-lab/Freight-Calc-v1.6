<#
.SYNOPSIS
  Installs the Australian English documentation and comment-only update.

.DESCRIPTION
  Updates project documentation and applies a Git patch that changes only
  comments and Python docstrings. It creates a timestamped backup before making
  any change. It does not change application logic, database files or Excel data.

.EXAMPLE
  .\install_language_update_0819.1336.ps1

.EXAMPLE
  .\install_language_update_0819.1336.ps1 -ProjectRoot "D:\Projects\Freight-Calc-Nuevo"
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\Docker-Projects\Freight-Calc-Nuevo"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DocumentationZip = Join-Path $PackageRoot "STH_documentation_Australian_English_0819.0832.zip"
$CommentPatch = Join-Path $PackageRoot "STH_comments_Australian_English_0819.0832.patch"
$Timestamp = Get-Date -Format "MMdd.HHmmss"
$TemporaryPath = Join-Path $env:TEMP "sth_language_update_$Timestamp"
$BackupDirectory = Join-Path $ProjectRoot "file_backups"
$BackupZip = Join-Path $BackupDirectory "before_language_update_$Timestamp.zip"

$CommentFiles = @(
    "Create_Files_Review_zip.ps1",
    "app\apps\authentication_gateway\forms.py",
    "app\apps\authentication_gateway\login_forms.py",
    "app\apps\authentication_gateway\views.py",
    "app\apps\carriers\models.py",
    "app\apps\clients\models.py",
    "app\apps\freight\management\commands\validate_excel_battery.py",
    "app\apps\freight\services\calculator.py",
    "app\apps\freight\services\consolidator.py",
    "app\apps\freight\services\resolvers.py",
    "app\apps\freight\services\tailgate_calculator.py",
    "app\apps\imports\management\commands\import_sth_excel.py",
    "app\apps\locations\models.py",
    "app\apps\products\models.py",
    "app\apps\rates\models.py",
    "app\static\css\app.css",
    "app\static\css\login.css"
)

function Assert-FileExists {
    param([string]$Path, [string]$Description)
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
}

function Invoke-GitCommand {
    param([string[]]$GitArguments)

    # Windows PowerShell 5 can convert stderr from a native command into a
    # NativeCommandError when ErrorActionPreference is Stop. A failed reverse
    # check is expected when a patch has not yet been installed, so capture the
    # process result explicitly and decide from Git's exit code instead.
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $CommandOutput = & git @GitArguments 2>&1
        $CommandExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    return [PSCustomObject]@{
        ExitCode = $CommandExitCode
        Output = ($CommandOutput | Out-String).Trim()
    }
}

if (!(Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project directory was not found: $ProjectRoot"
}
if (!(Test-Path -LiteralPath (Join-Path $ProjectRoot "app") -PathType Container)) {
    throw "The selected directory is not the expected project root because app\ is missing: $ProjectRoot"
}

Assert-FileExists -Path $DocumentationZip -Description "Documentation package"
Assert-FileExists -Path $CommentPatch -Description "Comment patch"

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to apply the comment-only patch. Install Git for Windows and run this installer again."
}

Write-Host "Checking compatibility with the current project files..." -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    $ReverseCheck = Invoke-GitCommand -GitArguments @("apply", "--reverse", "--check", $CommentPatch)
    $CommentsAlreadyInstalled = ($ReverseCheck.ExitCode -eq 0)

    if (!$CommentsAlreadyInstalled) {
        $ForwardCheck = Invoke-GitCommand -GitArguments @("apply", "--check", $CommentPatch)
        if ($ForwardCheck.ExitCode -ne 0) {
            throw "The comment patch does not match the current project files. No changes were installed.`n$($ForwardCheck.Output)"
        }
    }
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $TemporaryPath -Force | Out-Null
New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null

try {
    $DocumentationPath = Join-Path $TemporaryPath "documentation"
    $BackupStagingPath = Join-Path $TemporaryPath "backup"
    New-Item -ItemType Directory -Path $DocumentationPath -Force | Out-Null
    New-Item -ItemType Directory -Path $BackupStagingPath -Force | Out-Null
    Expand-Archive -LiteralPath $DocumentationZip -DestinationPath $DocumentationPath -Force

    $BackupItemCount = 0
    foreach ($RelativePath in @("README.md", "docs", "business_rules", "decisions") + $CommentFiles) {
        $SourcePath = Join-Path $ProjectRoot $RelativePath
        if (Test-Path -LiteralPath $SourcePath) {
            $DestinationPath = Join-Path $BackupStagingPath $RelativePath
            $DestinationParent = Split-Path -Parent $DestinationPath
            New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null

            if (Test-Path -LiteralPath $SourcePath -PathType Container) {
                New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
                Copy-Item -Path (Join-Path $SourcePath "*") -Destination $DestinationPath -Recurse -Force
            }
            else {
                Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
            }
            $BackupItemCount++
        }
    }

    if ($BackupItemCount -eq 0) {
        throw "No project files were found to back up. No changes were installed."
    }

    Write-Host "Creating backup: $BackupZip" -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $BackupStagingPath "*") -DestinationPath $BackupZip -Force

    Write-Host "Installing Australian English documentation..." -ForegroundColor Cyan
    Copy-Item -LiteralPath (Join-Path $DocumentationPath "README.md") -Destination (Join-Path $ProjectRoot "README.md") -Force

    foreach ($DirectoryName in @("docs", "business_rules", "decisions")) {
        $SourceDirectory = Join-Path $DocumentationPath $DirectoryName
        $DestinationDirectory = Join-Path $ProjectRoot $DirectoryName
        if (!(Test-Path -LiteralPath $DestinationDirectory)) {
            New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
        }
        Copy-Item -Path (Join-Path $SourceDirectory "*") -Destination $DestinationDirectory -Recurse -Force
    }

    if ($CommentsAlreadyInstalled) {
        Write-Host "The English comment update was already installed; it was not applied twice." -ForegroundColor Yellow
    }
    else {
        Write-Host "Applying the comment-only update..." -ForegroundColor Cyan
        Push-Location $ProjectRoot
        try {
            $ApplyResult = Invoke-GitCommand -GitArguments @("apply", $CommentPatch)
            if ($ApplyResult.ExitCode -ne 0) {
                throw "Git could not apply the comment-only patch. Restore the backup if required: $BackupZip`n$($ApplyResult.Output)"
            }
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "LANGUAGE UPDATE INSTALLED SUCCESSFULLY" -ForegroundColor Green
    Write-Host "Project: $ProjectRoot"
    Write-Host "Backup:  $BackupZip"
    Write-Host "Application logic, database and Excel data were not changed."
}
finally {
    if (Test-Path -LiteralPath $TemporaryPath) {
        Remove-Item -LiteralPath $TemporaryPath -Recurse -Force
    }
}
