from pathlib import Path
import win32com.client as win32

project_root = Path.cwd()
workbook_path = project_root / "generated_excel_baselines" / "debug_case_001" / "STH_LIVE_BASELINE_20260706_130237.xlsx"

# If the exact run-id file is not found, use the latest baseline in debug_case_001.
if not workbook_path.exists():
    files = sorted(
        (project_root / "generated_excel_baselines" / "debug_case_001").glob("STH_LIVE_BASELINE_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise SystemExit("No debug baseline workbook found.")
    workbook_path = files[0]

print("Workbook:")
print(workbook_path)
print("=" * 100)

excel = win32.DispatchEx("Excel.Application")
excel.Visible = True
excel.DisplayAlerts = False

try:
    wb = excel.Workbooks.Open(str(workbook_path.resolve()), UpdateLinks=0, ReadOnly=True)

    excel.Calculation = -4105  # xlCalculationAutomatic
    wb.ForceFullCalculation = True
    excel.CalculateFullRebuild()

    try:
        excel.CalculateUntilAsyncQueriesDone()
    except Exception:
        pass

    calc = wb.Worksheets("Calculator")

    print("Calculator key cells")
    print("-" * 100)

    cells = [
        "C7", "D7", "E7",
        "E11", "C13",
        "C15", "D15", "F15", "G15", "H15", "I15", "J15",
        "C16", "D16", "F16", "G16", "H16", "I16", "J16",
        "J12", "J23", "J24",
        "O5", "P5", "Q5",
        "O6", "P6", "Q6",
        "O7", "P7", "Q7",
        "O8", "P8", "Q8",
        "O9", "P9", "Q9",
    ]

    for addr in cells:
        print(f"Calculator!{addr} = {calc.Range(addr).Value}")

    print()
    print("CalcLines key cells")
    print("-" * 100)

    if "CalcLines" in [ws.Name for ws in wb.Worksheets]:
        cl = wb.Worksheets("CalcLines")
        for addr in ["L3", "E29", "F29", "M29", "N29", "O29", "P29", "Q29"]:
            print(f"CalcLines!{addr} = {cl.Range(addr).Value}")
    else:
        print("CalcLines sheet not found")

    print()
    print("FuelSurcharge key cells")
    print("-" * 100)

    if "FuelSurcharge" in [ws.Name for ws in wb.Worksheets]:
        fs = wb.Worksheets("FuelSurcharge")
        for addr in ["Q6", "Q7", "Q8", "Q9", "Q10", "Q11", "Q12"]:
            print(f"FuelSurcharge!{addr} = {fs.Range(addr).Value}")
    else:
        print("FuelSurcharge sheet not found")

    wb.Close(False)

finally:
    excel.Quit()
