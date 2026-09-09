param(
    [string]$Workbook = "sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx",
    [string]$Cases = "app\apps\freight\fixtures\sth_excel_validated_cases_0630.1428.csv",
    [string]$OutputDir = "generated_excel_baselines\latest",
    [switch]$Refresh,
    [switch]$Visible
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.venv-excel\Scripts\python.exe")) {
    throw "Missing .venv-excel. Create it and install pandas openpyxl pywin32 first."
}

$cmd = @(
    "tools\excel\generate_excel_expected_outputs.py",
    "--workbook", $Workbook,
    "--cases", $Cases,
    "--output-dir", $OutputDir,
    "--save-workbook"
)

if ($Refresh) { $cmd += "--refresh" }
if ($Visible) { $cmd += "--visible" }

& ".\.venv-excel\Scripts\python.exe" @cmd
