@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create_Continuity_Snapshot.ps1" %*
set "snapshot_exit=%errorlevel%"
if not "%snapshot_exit%"=="0" (
  echo [FAILED] Continuity Snapshot was not published. Exit code: %snapshot_exit%
  exit /b %snapshot_exit%
)
echo [OK] Continuity Snapshot published.
exit /b 0
