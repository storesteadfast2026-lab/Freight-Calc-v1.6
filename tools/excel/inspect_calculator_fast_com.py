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

print("Opening workbook:")
print(workbook_path)
print("=" * 100)

excel = win32.DispatchEx("Excel.Application")
excel.Visible = True
excel.DisplayAlerts = False

try:
    wb = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
    ws = wb.Worksheets("Calculator")

    excel.CalculateFullRebuild()

    print("Scanning Calculator only, rows 1 to 120, columns A to Z")
    print("=" * 100)

    keywords = [
        "KTI", "TEAMEX", "TFMX", "STEA", "COCHRN",
        "MIPEC", "TEAMTAS", "CUST",
        "ROAD", "GENERAL",
        "Estimate", "Carrier", "Service",
        "Freight", "ex GST", "GST"
    ]

    for r in range(1, 121):
        values = []
        row_has_hit = False

        for c in range(1, 27):  # A:Z
            cell = ws.Cells(r, c)
            value = cell.Value

            if value is None:
                continue

            text = str(value).strip()

            if not text:
                continue

            upper = text.upper()

            if any(k.upper() in upper for k in keywords):
                row_has_hit = True

            if isinstance(value, (int, float)) and 50 <= value <= 5000:
                row_has_hit = True

            addr = cell.Address.replace("$", "")
            values.append(f"{addr}={text}")

        if row_has_hit and values:
            print(" | ".join(values))

    wb.Close(False)

finally:
    excel.Quit()
