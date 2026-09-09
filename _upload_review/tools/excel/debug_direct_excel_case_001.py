from pathlib import Path
import time
import win32com.client as win32

project_root = Path.cwd()
workbook_path = project_root / "sample_data" / "V2026.R2_Unlocked_STH_Freight_Calculator.xlsx"
output_path = project_root / "generated_excel_baselines" / "debug_direct_case_001.xlsx"

print("Workbook:")
print(workbook_path)
print("=" * 100)

excel = None
wb = None

def safe_call(label, func):
    try:
        func()
        print(f"{label}: OK")
    except Exception as exc:
        print(f"{label}: skipped/error -> {exc}")

try:
    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = True
    excel.DisplayAlerts = False
    excel.EnableEvents = True

    wb = excel.Workbooks.Open(str(workbook_path.resolve()), UpdateLinks=0, ReadOnly=False)
    ws = wb.Worksheets("Calculator")

    # Load CASE_001 directly, without pandas and without the generator loop.
    ws.Range("C7").Value = "CAROLINE SPRINGS"
    ws.Range("D7").Value = "VIC"
    ws.Range("E11").Value = "NO"
    ws.Range("C13").Value = "YES"

    # Clear only SKU and Qty lines.
    for row in range(15, 23):
        ws.Range(f"C{row}").Value = ""
        ws.Range(f"D{row}").Value = ""

    # Write SKU as text/value.
    ws.Range("C15").NumberFormat = "@"
    ws.Range("C15").Value = "SMC30CABLED"
    ws.Range("D15").Value = 1

    # Recalculate using safe calls.
    safe_call("Worksheet Calculate", lambda: ws.Calculate())
    safe_call("Excel Calculate", lambda: excel.Calculate())
    safe_call("Excel CalculateFull", lambda: excel.CalculateFull())
    safe_call("Excel CalculateFullRebuild", lambda: excel.CalculateFullRebuild())
    safe_call("Async Queries Done", lambda: excel.CalculateUntilAsyncQueriesDone())

    time.sleep(2)

    print()
    print("Calculator cells after direct write")
    print("-" * 100)

    for addr in [
        "C7", "D7", "E7",
        "E11", "C13",
        "C15", "D15",
        "F15", "G15", "H15", "I15", "J15",
        "J12", "J23", "J24",
        "O5", "P5", "Q5",
        "O6", "P6", "Q6",
        "O7", "P7", "Q7",
        "O8", "P8", "Q8",
        "O9", "P9", "Q9",
    ]:
        print(f"Calculator!{addr} = {ws.Range(addr).Value}")

    print()
    print("CalcLines status")
    print("-" * 100)

    cl = wb.Worksheets("CalcLines")
    for addr in ["L3", "E29", "F29", "M29", "N29", "O29", "P29", "Q29"]:
        print(f"CalcLines!{addr} = {cl.Range(addr).Value}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.SaveCopyAs(str(output_path.resolve()))

    print()
    print("Saved debug copy:")
    print(output_path)

finally:
    if wb is not None:
        wb.Close(False)
    if excel is not None:
        excel.Quit()
