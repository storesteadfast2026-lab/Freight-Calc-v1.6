# Excel on-demand baseline generator

This package adds a Windows-only tool to generate validated expected outputs directly from Microsoft Excel desktop.

It does not change the Django app, database models, or calculation code.

## Files

Copy files to:

- `tools\excel\generate_excel_expected_outputs.py`
- `tools\excel\run_generate_excel_baseline.ps1`

## Requirements

Run on Windows, not inside Docker.

The `.venv-excel` environment must contain:

```powershell
pip install pandas openpyxl pywin32
```

Microsoft Excel desktop must be installed.

## Basic run

From `C:\Docker-Projects\Freight-Calc-05jun`:

```powershell
.\.venv-excel\Scripts\activate

.\tools\excel\run_generate_excel_baseline.ps1 `
  -Workbook "sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx" `
  -Cases "app\apps\freight\fixtures\sth_excel_validated_cases_0630.1428.csv" `
  -OutputDir "generated_excel_baselines\latest"
```

To refresh Excel online connections first:

```powershell
.\tools\excel\run_generate_excel_baseline.ps1 `
  -Workbook "sample_data\V2026.R2_Unlocked_STH_Freight_Calculator.xlsx" `
  -Cases "app\apps\freight\fixtures\sth_excel_validated_cases_0630.1428.csv" `
  -OutputDir "generated_excel_baselines\latest" `
  -Refresh
```

## Generated files

The output directory will contain:

- `sth_excel_generated_cases.csv`
- `sth_excel_generated_outputs.csv`
- `sth_excel_generated_components.csv`
- `manifest.json`
- `STH_LIVE_BASELINE_<run_id>.xlsx` if `--save-workbook` is used

## Next step after generation

Import the same generated workbook into Django/PostgreSQL, then run `validate_excel_battery` using the generated CSV files.
