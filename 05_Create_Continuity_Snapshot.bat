@echo off
setlocal
set "snapshot_tool=%~dp0tools\Create_Continuity_Snapshot.bat"
if not exist "%snapshot_tool%" set "snapshot_tool=C:\Docker-Projects\Freight-Calc-v1.6\tools\Create_Continuity_Snapshot.bat"
if not exist "%snapshot_tool%" (
  echo [FAILED] Calculator App Continuity Snapshot tool is not installed: %snapshot_tool%
  exit /b 1
)
call "%snapshot_tool%" %*
set "snapshot_exit=%errorlevel%"
if not "%snapshot_exit%"=="0" (
  echo [FAILED] Manual Continuity Snapshot failed. The previous LATEST remains available.
  exit /b %snapshot_exit%
)
echo [OK] Manual Continuity Snapshot completed. The versioned and LATEST paths are shown above.
exit /b 0
