"""
Generate on-demand Excel expected outputs for the STH freight calculator.

Runs on Windows outside Docker because it controls Microsoft Excel through pywin32.

V4 design:
- Uses csv.DictReader instead of pandas for the case loop.
- Opens a fresh workbook for each case, matching the direct COM diagnostic that worked.
- Writes SKU/Qty exactly to Calculator!C15:D22.
- Writes numeric SKU codes as numbers and alphanumeric SKU codes as text.
  This is required because the STH workbook product lookup treats codes like 20772 as numeric IDs.
- Forces recalculation with the same sequence proven in debug_direct_excel_case_001.py.
- Writes a debug CSV including formula/status cells, so failures are visible.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import win32com.client as win32

DEFAULT_SHEET = "Calculator"

DEFAULT_INPUT_CELLS = {
    "suburb": "C7",
    "state": "D7",
    "postcode": "E7",
    "tailgate": "E11",
    "preselect_sku_mode": "C13",
    "sku_start_cell": "C15",
    "qty_start_cell": "D15",
    "line_count": 8,
}

DEFAULT_OUTPUT_CELLS = {
    "rank_start_row": 6,
    "carrier_col": "O",
    "service_col": "P",
    "estimate_col": "Q",
    "rank_count": 4,
    "total_weight_cell": "J23",
    "total_cubic_cell": "J24",
}

OUTPUT_FIELDNAMES = [
    "case_id",
    "rank",
    "expected_carrier",
    "expected_service",
    "expected_estimate_ex_gst",
    "validation_status",
    "source",
    "notes",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    if text.endswith(".0"):
        base = text[:-2]
        if base.isdigit():
            return base
    return text


def norm_bool_text(value: Any, default: str = "NO") -> str:
    text = clean_text(value).upper()
    if not text:
        text = default.upper()
    if text in {"Y", "YES", "TRUE", "1"}:
        return "YES"
    if text in {"N", "NO", "FALSE", "0"}:
        return "NO"
    return text


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = clean_text(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_money_text(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return ""
    return f"{number:.2f}"


def carrier_code(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return text.split("-")[0].strip().upper()


def service_code(value: Any) -> str:
    return clean_text(value).upper()


def load_cases(path: Path, case_id: Optional[str] = None) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [{k: clean_text(v) for k, v in row.items()} for row in reader]

    if not rows:
        raise ValueError(f"No case rows found in cases CSV: {path}")

    if "case_id" not in rows[0]:
        raise ValueError(f"Missing case_id column in cases CSV: {path}")

    if case_id:
        rows = [row for row in rows if clean_text(row.get("case_id")) == case_id]
        if not rows:
            raise ValueError(f"case_id not found in cases CSV: {case_id}")

    return rows


def collect_sku_lines(row: Dict[str, str], max_lines: int) -> List[Dict[str, str]]:
    lines: List[Dict[str, str]] = []
    for idx in range(1, max_lines + 1):
        sku = clean_text(row.get(f"sku_{idx}", ""))
        qty = clean_text(row.get(f"qty_{idx}", ""))
        if sku:
            lines.append({"sku": sku, "qty": qty or "1"})
    return lines


def sku_excel_write_value(sku: Any) -> Dict[str, Any]:
    """Return the exact value/format to write into Calculator SKU cells.

    The STH workbook has mixed SKU identifiers:
    - alphanumeric codes such as SMC30CABLED must be written as text
    - numeric product codes such as 20772 must be written as numbers

    If numeric SKUs are forced to text, Excel lookup formulas do not match the
    product table and CalcLines!L3 becomes STOP.
    """
    text = clean_text(sku)
    if text.isdigit() and (text == "0" or not text.startswith("0")):
        return {"value": int(text), "number_format": "General", "write_type": "numeric"}
    return {"value": text, "number_format": "@", "write_type": "text"}


def get_cell(ws: Any, address: str) -> Any:
    return ws.Range(address).Value


def set_cell(ws: Any, address: str, value: Any) -> None:
    ws.Range(address).Value = value


def safe_excel_call(label: str, func: Any, verbose: bool = False) -> None:
    try:
        func()
        if verbose:
            print(f"{label}: OK")
    except Exception as exc:
        if verbose:
            print(f"{label}: skipped/error -> {exc}")


def wait_for_excel(excel: Any, seconds: float = 0.25) -> None:
    time.sleep(seconds)
    for _ in range(120):
        try:
            if excel.CalculationState == 0:
                break
        except Exception:
            break
        time.sleep(0.25)


def force_calculate(excel: Any, ws: Any, verbose: bool = False) -> None:
    safe_excel_call("Worksheet Calculate", lambda: ws.Calculate(), verbose)
    safe_excel_call("Excel Calculate", lambda: excel.Calculate(), verbose)
    safe_excel_call("Excel CalculateFull", lambda: excel.CalculateFull(), verbose)
    safe_excel_call("Excel CalculateFullRebuild", lambda: excel.CalculateFullRebuild(), verbose)
    safe_excel_call("Async Queries Done", lambda: excel.CalculateUntilAsyncQueriesDone(), verbose)
    time.sleep(2.0)
    wait_for_excel(excel, 0.5)


def write_case_inputs(ws: Any, excel: Any, row: Dict[str, str], args: argparse.Namespace) -> Dict[str, Any]:
    case_id = clean_text(row.get("case_id"))

    set_cell(ws, args.suburb_cell, clean_text(row.get("suburb")))
    set_cell(ws, args.state_cell, clean_text(row.get("state")))
    set_cell(ws, args.postcode_cell, clean_text(row.get("postcode")))
    set_cell(ws, args.tailgate_cell, norm_bool_text(row.get("tailgate", "NO")))
    set_cell(ws, args.preselect_cell, norm_bool_text(row.get("preselect_sku_mode", "YES"), default="YES"))

    # Clear only C15:D22. Leave formula columns untouched.
    for excel_row in range(15, 15 + int(args.line_count)):
        ws.Range(f"C{excel_row}").Value = ""
        ws.Range(f"D{excel_row}").Value = ""

    lines = collect_sku_lines(row, int(args.line_count))
    for index, line in enumerate(lines):
        excel_row = 15 + index
        sku_cell = ws.Range(f"C{excel_row}")
        qty_cell = ws.Range(f"D{excel_row}")

        sku_write = sku_excel_write_value(line["sku"])
        try:
            sku_cell.NumberFormat = sku_write["number_format"]
        except Exception:
            pass
        sku_cell.Value = sku_write["value"]

        qty_number = safe_float(line["qty"])
        if qty_number is None:
            qty_cell.Value = line["qty"]
        else:
            qty_cell.Value = int(qty_number) if qty_number.is_integer() else qty_number

    force_calculate(excel, ws, verbose=bool(args.visible))

    debug: Dict[str, Any] = {
        "case_id": case_id,
        "suburb_written": clean_text(row.get("suburb")),
        "state_written": clean_text(row.get("state")),
        "postcode_written": clean_text(row.get("postcode")),
        "tailgate_written": norm_bool_text(row.get("tailgate", "NO")),
        "preselect_written": norm_bool_text(row.get("preselect_sku_mode", "YES"), default="YES"),
        "suburb_readback": clean_text(get_cell(ws, args.suburb_cell)),
        "state_readback": clean_text(get_cell(ws, args.state_cell)),
        "postcode_readback": clean_text(get_cell(ws, args.postcode_cell)),
        "tailgate_readback": clean_text(get_cell(ws, args.tailgate_cell)),
        "preselect_readback": clean_text(get_cell(ws, args.preselect_cell)),
        "formula_len_1": clean_text(get_cell(ws, "F15")),
        "formula_width_1": clean_text(get_cell(ws, "G15")),
        "formula_height_1": clean_text(get_cell(ws, "H15")),
        "formula_weight_1": clean_text(get_cell(ws, "I15")),
        "formula_cubic_1": clean_text(get_cell(ws, "J15")),
        "total_weight_readback": clean_text(get_cell(ws, args.total_weight_cell)),
        "total_cubic_readback": clean_text(get_cell(ws, args.total_cubic_cell)),
    }

    for idx in range(1, int(args.line_count) + 1):
        offset = idx - 1
        excel_row = 15 + offset
        expected_sku = lines[offset]["sku"] if offset < len(lines) else ""
        expected_qty = lines[offset]["qty"] if offset < len(lines) else ""
        expected_sku_type = sku_excel_write_value(expected_sku)["write_type"] if expected_sku else ""
        debug[f"expected_sku_{idx}"] = expected_sku
        debug[f"expected_sku_type_{idx}"] = expected_sku_type
        debug[f"expected_qty_{idx}"] = expected_qty
        debug[f"actual_sku_{idx}"] = clean_text(get_cell(ws, f"C{excel_row}"))
        debug[f"actual_qty_{idx}"] = clean_text(get_cell(ws, f"D{excel_row}"))

    try:
        cl = ws.Parent.Worksheets("CalcLines")
        debug["calclines_l3_status"] = clean_text(get_cell(cl, "L3"))
        debug["calclines_o29_weight"] = clean_text(get_cell(cl, "O29"))
        debug["calclines_p29_cubic"] = clean_text(get_cell(cl, "P29"))
    except Exception as exc:
        debug["calclines_l3_status"] = f"ERROR: {exc}"

    return debug


def read_rank_outputs(ws: Any, row: Dict[str, str], args: argparse.Namespace) -> List[Dict[str, str]]:
    count_text = clean_text(row.get("expected_rank_count"))
    rank_count = int(float(count_text)) if count_text else int(args.rank_count)
    outputs: List[Dict[str, str]] = []

    for rank in range(1, rank_count + 1):
        excel_row = int(args.rank_start_row) + rank - 1
        carrier = carrier_code(get_cell(ws, f"{args.carrier_col}{excel_row}"))
        service = service_code(get_cell(ws, f"{args.service_col}{excel_row}"))
        estimate = safe_money_text(get_cell(ws, f"{args.estimate_col}{excel_row}"))

        if not carrier and not service and not estimate:
            continue

        outputs.append({
            "case_id": clean_text(row.get("case_id")),
            "rank": str(rank),
            "expected_carrier": carrier,
            "expected_service": service,
            "expected_estimate_ex_gst": estimate,
            "validation_status": "generated_from_excel_live",
            "source": "Microsoft Excel automation",
            "notes": "Generated on demand from live Excel workbook.",
        })

    return outputs


def read_components(ws: Any, row: Dict[str, str], first_output: Optional[Dict[str, str]], args: argparse.Namespace) -> Dict[str, str]:
    first = first_output or {}
    return {
        "case_id": clean_text(row.get("case_id")),
        "total_weight_kg": clean_text(get_cell(ws, args.total_weight_cell)),
        "total_cubic_m3": clean_text(get_cell(ws, args.total_cubic_cell)),
        "selected_carrier": first.get("expected_carrier", ""),
        "selected_service": first.get("expected_service", ""),
        "selected_estimate_ex_gst": first.get("expected_estimate_ex_gst", ""),
        "measured_postcode_from_excel": clean_text(get_cell(ws, args.postcode_cell)),
        "validation_status": "generated_from_excel_live",
        "source": "Microsoft Excel automation",
        "notes": "Totals read from configured Calculator cells.",
    }


def write_csv(path: Path, rows: List[Dict[str, Any]], default_fieldnames: Optional[List[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(default_fieldnames or [])
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def prepare_baseline_copy(excel: Any, workbook_path: Path, output_dir: Path, run_id: str, refresh: bool) -> Path:
    baseline_path = output_dir / f"STH_LIVE_BASELINE_{run_id}.xlsx"

    if refresh:
        wb = excel.Workbooks.Open(str(workbook_path.resolve()), UpdateLinks=0, ReadOnly=False)
        try:
            print("Running Excel RefreshAll...")
            wb.RefreshAll()
            safe_excel_call("Async Queries Done", lambda: excel.CalculateUntilAsyncQueriesDone(), True)
            wait_for_excel(excel, 2.0)
            wb.SaveCopyAs(str(baseline_path.resolve()))
        finally:
            wb.Close(False)
    else:
        shutil.copy2(workbook_path, baseline_path)

    return baseline_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Excel expected outputs from live Microsoft Excel.")
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--save-workbook", action="store_true")
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--run-id", default=None)

    parser.add_argument("--sheet", default=DEFAULT_SHEET)
    parser.add_argument("--suburb-cell", default=DEFAULT_INPUT_CELLS["suburb"])
    parser.add_argument("--state-cell", default=DEFAULT_INPUT_CELLS["state"])
    parser.add_argument("--postcode-cell", default=DEFAULT_INPUT_CELLS["postcode"])
    parser.add_argument("--tailgate-cell", default=DEFAULT_INPUT_CELLS["tailgate"])
    parser.add_argument("--preselect-cell", default=DEFAULT_INPUT_CELLS["preselect_sku_mode"])
    parser.add_argument("--sku-start-cell", default=DEFAULT_INPUT_CELLS["sku_start_cell"])
    parser.add_argument("--qty-start-cell", default=DEFAULT_INPUT_CELLS["qty_start_cell"])
    parser.add_argument("--line-count", type=int, default=DEFAULT_INPUT_CELLS["line_count"])

    parser.add_argument("--rank-start-row", type=int, default=DEFAULT_OUTPUT_CELLS["rank_start_row"])
    parser.add_argument("--carrier-col", default=DEFAULT_OUTPUT_CELLS["carrier_col"])
    parser.add_argument("--service-col", default=DEFAULT_OUTPUT_CELLS["service_col"])
    parser.add_argument("--estimate-col", default=DEFAULT_OUTPUT_CELLS["estimate_col"])
    parser.add_argument("--rank-count", type=int, default=DEFAULT_OUTPUT_CELLS["rank_count"])
    parser.add_argument("--total-weight-cell", default=DEFAULT_OUTPUT_CELLS["total_weight_cell"])
    parser.add_argument("--total-cubic-cell", default=DEFAULT_OUTPUT_CELLS["total_cubic_cell"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path.cwd()

    workbook_path = Path(args.workbook)
    cases_path = Path(args.cases)
    output_dir = Path(args.output_dir)

    if not workbook_path.is_absolute():
        workbook_path = project_root / workbook_path
    if not cases_path.is_absolute():
        cases_path = project_root / cases_path
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    if not workbook_path.exists():
        raise SystemExit(f"Workbook not found: {workbook_path}")
    if not cases_path.exists():
        raise SystemExit(f"Cases CSV not found: {cases_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    cases = load_cases(cases_path, args.case_id)

    print(f"Workbook: {workbook_path}")
    print(f"Cases: {cases_path}")
    print(f"Output dir: {output_dir}")
    print(f"Run id: {run_id}")
    print(f"Cases to run: {len(cases)}")

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = bool(args.visible)
    excel.DisplayAlerts = False
    try:
        excel.EnableEvents = True
    except Exception:
        pass

    generated_cases: List[Dict[str, Any]] = []
    generated_outputs: List[Dict[str, Any]] = []
    generated_components: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []
    workbook_copy = ""

    try:
        source_for_cases = workbook_path
        if args.save_workbook or args.refresh:
            source_for_cases = prepare_baseline_copy(excel, workbook_path, output_dir, run_id, args.refresh)
            workbook_copy = str(source_for_cases)

        for row in cases:
            case_id = clean_text(row.get("case_id"))
            print(f"Running {case_id}...")

            wb = None
            try:
                wb = excel.Workbooks.Open(str(source_for_cases.resolve()), UpdateLinks=0, ReadOnly=False)
                ws = wb.Worksheets(args.sheet)

                debug = write_case_inputs(ws, excel, row, args)
                outputs = read_rank_outputs(ws, row, args)
                component = read_components(ws, row, outputs[0] if outputs else None, args)

                case_dict = {key: clean_text(value) for key, value in row.items()}
                case_dict["measured_postcode_from_excel"] = clean_text(get_cell(ws, args.postcode_cell))
                case_dict["generated_validation_status"] = "generated_from_excel_live"
                case_dict["generated_output_count"] = str(len(outputs))

                debug["generated_output_count"] = str(len(outputs))
                debug["rank1_carrier_readback"] = carrier_code(get_cell(ws, f"{args.carrier_col}{args.rank_start_row}"))
                debug["rank1_service_readback"] = service_code(get_cell(ws, f"{args.service_col}{args.rank_start_row}"))
                debug["rank1_estimate_readback"] = safe_money_text(get_cell(ws, f"{args.estimate_col}{args.rank_start_row}"))

                generated_cases.append(case_dict)
                generated_outputs.extend(outputs)
                generated_components.append(component)
                debug_rows.append(debug)

            finally:
                if wb is not None:
                    wb.Close(False)

    finally:
        excel.Quit()

    cases_out = output_dir / "sth_excel_generated_cases.csv"
    outputs_out = output_dir / "sth_excel_generated_outputs.csv"
    components_out = output_dir / "sth_excel_generated_components.csv"
    debug_out = output_dir / "sth_excel_generation_debug.csv"
    manifest_out = output_dir / "manifest.json"

    write_csv(cases_out, generated_cases)
    write_csv(outputs_out, generated_outputs, default_fieldnames=OUTPUT_FIELDNAMES)
    write_csv(components_out, generated_components)
    write_csv(debug_out, debug_rows)

    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workbook_source": str(workbook_path),
        "cases_source": str(cases_path),
        "source_for_cases": str(source_for_cases),
        "refresh_all": bool(args.refresh),
        "save_workbook": bool(args.save_workbook),
        "workbook_copy": workbook_copy,
        "cases_run": len(generated_cases),
        "outputs_generated": len(generated_outputs),
        "components_generated": len(generated_components),
        "debug_rows_generated": len(debug_rows),
        "excel_sheet": args.sheet,
        "input_cells": {
            "suburb": args.suburb_cell,
            "state": args.state_cell,
            "postcode": args.postcode_cell,
            "tailgate": args.tailgate_cell,
            "preselect": args.preselect_cell,
            "sku_start": args.sku_start_cell,
            "qty_start": args.qty_start_cell,
            "line_count": args.line_count,
        },
        "output_cells": {
            "rank_start_row": args.rank_start_row,
            "carrier_col": args.carrier_col,
            "service_col": args.service_col,
            "estimate_col": args.estimate_col,
            "rank_count": args.rank_count,
            "total_weight_cell": args.total_weight_cell,
            "total_cubic_cell": args.total_cubic_cell,
        },
    }
    manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Generated files:")
    for path in [cases_out, outputs_out, components_out, debug_out, manifest_out]:
        print(f"  {path}")
    if workbook_copy:
        print(f"  {workbook_copy}")


if __name__ == "__main__":
    main()
