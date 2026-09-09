[CmdletBinding()]
param(
    [string]$ScriptsFolder = $PSScriptRoot,
    [string]$TaskName = "FreightCalc Daily Backup",
    [string]$DailyTime = "19:00",
    [string]$ProjectRoot = "C:\Docker-Projects\Freight-Calc-v1.5",
    [string]$BackupRoot = "C:\Docker-Backups\Freight-Calc",
    [string]$SecondaryCopyPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Write-TaskSummary {
    param([string]$Name)

    Write-Host "`n=== TASK DETAILS ==="
    Get-ScheduledTask -TaskName $Name -ErrorAction Stop |
        Select-Object TaskName, State, Description

    Write-Host "`n=== NEXT RUN INFORMATION ==="
    Get-ScheduledTaskInfo -TaskName $Name -ErrorAction Stop |
        Select-Object LastRunTime, LastTaskResult, NextRunTime
}

$backupScript = Join-Path $ScriptsFolder "01_Full_Backup.ps1"

if (-not (Test-Path $backupScript)) {
    throw "Backup script not found: $backupScript"
}

if ($DailyTime -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d$') {
    throw "DailyTime must use 24-hour HH:mm format, for example 19:00."
}

if (-not (Test-Path $ProjectRoot)) {
    throw "Project root does not exist: $ProjectRoot"
}

$timeParts = $DailyTime.Split(":")
$hour = [int]$timeParts[0]
$minute = [int]$timeParts[1]
$triggerTime = (Get-Date).Date.AddHours($hour).AddMinutes($minute)

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$isAdministrator = Test-IsAdministrator

Write-Host "============================================================"
Write-Host " INSTALL DAILY FREIGHT CALCULATOR BACKUP TASK"
Write-Host "============================================================"
Write-Host "Task name       : $TaskName"
Write-Host "Windows user    : $currentUser"
Write-Host "Daily time      : $DailyTime"
Write-Host "Backup script   : $backupScript"
Write-Host "Project root    : $ProjectRoot"
Write-Host "Backup root     : $BackupRoot"
Write-Host "Administrator   : $isAdministrator"
Write-Host ""
Write-Host "IMPORTANT:"
Write-Host "- Docker Desktop and the project containers must be available when it runs."
Write-Host "- The task runs only while this Windows user is logged on."
Write-Host "- The task is registered with LIMITED user privileges by design."
Write-Host "- Administrator access is not required for the default configuration."

$argumentParts = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$backupScript`"",
    "-ProjectRoot", "`"$ProjectRoot`"",
    "-BackupRoot", "`"$BackupRoot`""
)

if (-not [string]::IsNullOrWhiteSpace($SecondaryCopyPath)) {
    $argumentParts += @(
        "-SecondaryCopyPath",
        "`"$SecondaryCopyPath`""
    )
}

$argumentString = $argumentParts -join " "

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $argumentString

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At $triggerTime

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# LIMITED + Interactive avoids unnecessary elevation and is appropriate for
# Docker Desktop running in the signed-in user's Windows session.
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

Write-Host "`n=== REGISTERING TASK ==="

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force `
        -ErrorAction Stop | Out-Null
}
catch {
    Write-Host ""
    Write-Host "ERROR - The scheduled task could not be registered."
    Write-Host "Windows message: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "No backup task was installed."
    throw
}

Write-Host "OK - Scheduled task registered successfully."

Write-TaskSummary -Name $TaskName

Write-Host "`n=== COMPLETE ==="
Write-Host "Daily backup automation is installed."
