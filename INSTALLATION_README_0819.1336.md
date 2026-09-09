# STH Language Update Installer

This package installs the Australian English documentation and the comment-only
source update for STH Freight Calculator.

This version replaces `0819.1318` and corrects Windows PowerShell handling of
expected Git compatibility-check output.

## Scope

- replaces or overlays `README.md`, `docs/`, `business_rules/` and `decisions/`;
- applies English/Australian spelling changes to comments and Python docstrings;
- keeps `docs/20_ai_project_continuation_prompt.md` in Spanish;
- does not change application logic, database files, Excel files or runtime data;
- creates a timestamped ZIP backup under `file_backups/` before installation.

## Installation

Extract the complete ZIP and keep all four package files together. Open
PowerShell in the extracted directory and run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\install_language_update_0819.1336.ps1"
```

The default project location is:

```text
C:\Docker-Projects\Freight-Calc-Nuevo
```

For another location:

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\install_language_update_0819.1336.ps1" -ProjectRoot "D:\Projects\Freight-Calc-Nuevo"
```

Git for Windows must be available because the comments are installed as a
validated patch rather than by replacing complete application source files.
