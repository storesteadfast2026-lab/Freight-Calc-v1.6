from pathlib import Path
import win32com.client as win32

project_root = Path.cwd()
baseline_dir = project_root / "generated_excel_baselines" / "latest"

workbooks = sorted(
    baseline_dir.glob("STH_LIVE_BASELINE_*.xlsx"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not workbooks:
    raise SystemExit(f"No baseline workbook found in: {baseline_dir}")

workbook_path = workbooks[0].resolve()

excel = win32.DispatchEx("Excel.Application")
excel.Visible = True
excel.DisplayAlerts = False

try:
    wb = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
    ws = wb.Worksheets("Calculator")

    print("Workbook:")
    print(workbook_path)
    print("=" * 80)

    cells = [
        "C7", "D7", "E7",
        "E11", "C13",
        "C15", "D15",
        "C16", "D16",
        "C17", "D17",
        "C18", "D18",
        "I12", "J12",
        "I24", "J24",
        "O5", "P5", "Q5",
        "O6", "P6", "Q6",
        "O7", "P7", "Q7",
        "O8", "P8", "Q8",
    ]

    for addr in cells:
        print(f"{addr} = {ws.Range(addr).Value}")

    wb.Close(False)

finally:
    excel.Quit()
