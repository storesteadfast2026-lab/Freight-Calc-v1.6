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

carrier_codes = [
    "KTI",
    "TEAMEX",
    "TFMX",
    "STEA",
    "COCHRN",
    "MIPEC",
    "TEAMTAS",
    "CUST",
]

keywords = [
    "Estimate",
    "Freight",
    "Carrier",
    "Service",
    "ROAD",
    "GENERAL",
    "COCHRN",
    "TEAMEX",
    "KTI",
    "TFMX",
    "STEA",
]

print(f"Opening workbook with Microsoft Excel:")
print(workbook_path)
print("=" * 100)

excel = win32.DispatchEx("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False

try:
    wb = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
    excel.CalculateFullRebuild()

    for ws in wb.Worksheets:
        used = ws.UsedRange
        rows = used.Rows.Count
        cols = used.Columns.Count
        start_row = used.Row
        start_col = used.Column

        hits = []

        for r in range(start_row, start_row + rows):
            for c in range(start_col, start_col + cols):
                cell = ws.Cells(r, c)
                value = cell.Value

                if value is None:
                    continue

                text = str(value).strip()

                if not text:
                    continue

                upper = text.upper()

                if any(code in upper for code in carrier_codes) or any(k.upper() in upper for k in keywords):
                    hits.append((r, c, cell.Address.replace("$", ""), text))

        if hits:
            print()
            print(f"SHEET: {ws.Name}")
            print("-" * 100)

            for r, c, addr, text in hits[:200]:
                print(f"{addr} = {text}")

            print()
            print(f"Context rows around hits in sheet: {ws.Name}")
            print("-" * 100)

            seen_rows = sorted(set(r for r, _, _, _ in hits))
            for r in seen_rows[:50]:
                values = []
                for c in range(1, min(cols + 1, 35)):
                    value = ws.Cells(r, c).Value
                    if value is not None and str(value).strip() != "":
                        addr = ws.Cells(r, c).Address.replace("$", "")
                        values.append(f"{addr}={value}")
                if values:
                    print(" | ".join(values))

    wb.Close(False)

finally:
    excel.Quit()
