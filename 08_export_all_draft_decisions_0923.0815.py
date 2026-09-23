# Work.Calc / Freight Calculator
# SCRIPT 08 - READ ONLY
# Exports all current Product reconciliation draft decisions for review.
# NO database changes are made.

from django.apps import apps
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv, json, re

TARGET_FILENAME = "products.xls"
CSV_PATH = Path("/tmp/draft_decisions_229_0923.0815.csv")
DIAG_PATH = Path("/tmp/draft_decision_diagnostics_0923.0815.txt")

DECISION_KEYS = {"name", "description", "dimensions", "weight", "cubic", "freight_type"}
DECISION_VALUES = {"SOURCE", "OPERATIONAL"}
HINTS = ("draft", "decision", "repair", "approv", "reconcil", "resolution", "rule", "memory")


def find_model(name):
    for m in apps.get_models():
        if m.__name__ == name:
            return m
    raise RuntimeError(f"Model not found: {name}")


def cfields(model):
    return [f for f in model._meta.get_fields() if getattr(f, "concrete", False) and not getattr(f, "many_to_many", False)]


def fnames(model):
    return {f.name for f in cfields(model)}


def first(existing, candidates):
    return next((c for c in candidates if c in existing), None)


def txt(v):
    return "" if v is None else str(v).strip()


def dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def same_num(a, b, tol=Decimal("0.000001")):
    a, b = dec(a), dec(b)
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def mm_to_m(v):
    v = dec(v)
    return None if v is None else v / Decimal("1000")


def m_to_mm(v):
    v = dec(v)
    return None if v is None else v * Decimal("1000")


def raw_value(row, key):
    raw = getattr(row, "raw_data", None)
    if not isinstance(raw, dict):
        return None
    lower = {str(k).strip().lower(): v for k, v in raw.items()}
    return lower.get(key.lower())


def jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    return str(v)


def serialize(obj):
    out = {"_model": obj._meta.label, "_pk": getattr(obj, "pk", None)}
    for f in cfields(obj.__class__):
        try:
            out[f.name] = getattr(obj, f.attname, None) if getattr(f, "is_relation", False) else jsonable(getattr(obj, f.name, None))
        except Exception as exc:
            out[f.name] = f"<ERROR:{exc}>"
    return out


def relevant_model(model):
    blob = (model.__name__ + " " + model._meta.label + " " + " ".join(fnames(model))).lower()
    return any(h in blob for h in HINTS)


def related_payloads(row):
    payloads = []
    seen = set()
    for f in row._meta.get_fields():
        if not getattr(f, "is_relation", False):
            continue
        model = getattr(f, "related_model", None)
        if not model or not relevant_model(model):
            continue
        objs = []
        if getattr(f, "concrete", False):
            try:
                obj = getattr(row, f.name, None)
                if obj is not None:
                    objs = [obj]
            except Exception:
                pass
        else:
            try:
                accessor = f.get_accessor_name()
                value = getattr(row, accessor)
                objs = list(value.all()) if hasattr(value, "all") else ([value] if value is not None else [])
            except Exception:
                pass
        for obj in objs:
            key = (obj._meta.label, getattr(obj, "pk", id(obj)))
            if key not in seen:
                seen.add(key)
                payloads.append(serialize(obj))
    return payloads


def maybe_json(v):
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str) and v.strip()[:1] in ("{", "["):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def find_decision(v):
    v = maybe_json(v)
    if isinstance(v, dict):
        d = {}
        for k, x in v.items():
            kk, vv = str(k).strip().lower(), txt(x).upper()
            if kk in DECISION_KEYS and vv in DECISION_VALUES:
                d[kk] = vv
        if d:
            return d
        for x in v.values():
            found = find_decision(x)
            if found:
                return found
    elif isinstance(v, list):
        for x in v:
            found = find_decision(x)
            if found:
                return found
    return {}


def scale_warning(source_mm, operational_m):
    ratios = []
    for src, opm in zip(source_mm, operational_m):
        src, ref = dec(src), m_to_mm(opm)
        if src is None or ref is None or src <= 0 or ref <= 0:
            continue
        ratios.append(src / ref)
    if len(ratios) >= 2:
        if sum(Decimal("8.5") <= r <= Decimal("11.5") for r in ratios) >= 2:
            return "TL_APPROX_10X_OPERATIONAL"
        if sum(Decimal("0.085") <= r <= Decimal("0.115") for r in ratios) >= 2:
            return "TL_APPROX_0.1X_OPERATIONAL"
    return ""


Product = find_model("Product")
SourceRow = find_model("ProductSourceRow")
PF, SF = fnames(Product), fnames(SourceRow)

P_SKU = first(PF, ["sku", "code", "product_code"])
P_NAME = first(PF, ["name", "product_name"])
P_DESC = first(PF, ["description", "desc"])
P_L = first(PF, ["length_m", "length"])
P_W = first(PF, ["width_m", "width"])
P_H = first(PF, ["height_m", "height"])
P_WEIGHT = first(PF, ["weight_kg", "weight"])
P_CUBIC = first(PF, ["cubic_m3", "cubic"])
P_CP = first(PF, ["freight_type", "type"])

S_SKU = first(SF, ["product_code_normalized", "sku_normalized", "code_normalized", "sku", "code", "product_code"])
S_NAME = first(SF, ["name", "product_name"])
S_DESC = first(SF, ["description", "desc"])
S_L = first(SF, ["length_mm", "length"])
S_W = first(SF, ["width_mm", "width"])
S_H = first(SF, ["height_mm", "height"])
S_WEIGHT = first(SF, ["weight_kg", "weight"])
S_CUBIC = first(SF, ["cubic_m3", "cubic"])
S_PALLET = first(SF, ["pallet"])

# Latest products.xls
rel_field = None
for f in SourceRow._meta.get_fields():
    if getattr(f, "many_to_one", False):
        model = getattr(f, "related_model", None)
        if model and "original_filename" in fnames(model):
            rel_field = f.name
            break
if not rel_field:
    raise RuntimeError("Could not locate ProductSourceRow -> ExternalDataFile relation")

ExternalFile = SourceRow._meta.get_field(rel_field).related_model
ext = ExternalFile.objects.filter(original_filename__iexact=TARGET_FILENAME).order_by("-pk").first()
if not ext:
    raise RuntimeError("products.xls not found")

source_qs = SourceRow.objects.filter(**{rel_field: ext})
sources = {txt(getattr(s, S_SKU, "")): s for s in source_qs.iterator() if txt(getattr(s, S_SKU, ""))}
products = {txt(getattr(p, P_SKU, "")): p for p in Product.objects.all() if txt(getattr(p, P_SKU, ""))}
matched = sorted(set(products) & set(sources))

rows = []
safe = review = unknown = parsed = 0

for sku in matched:
    p, s = products[sku], sources[sku]
    payloads = related_payloads(s)

    # Also scan direct decision-like fields on ProductSourceRow.
    for f in cfields(SourceRow):
        if any(k in f.name.lower() for k in ("draft", "decision", "repair", "resolution")):
            payloads.append({"_model": SourceRow._meta.label, "_field": f.name, "value": jsonable(getattr(s, f.name, None))})

    decision = {}
    for payload in payloads:
        decision = find_decision(payload)
        if decision:
            break
    if decision:
        parsed += 1

    src_l_mm, src_w_mm, src_h_mm = dec(getattr(s, S_L, None)), dec(getattr(s, S_W, None)), dec(getattr(s, S_H, None))
    op_l, op_w, op_h = dec(getattr(p, P_L, None)), dec(getattr(p, P_W, None)), dec(getattr(p, P_H, None))
    src_weight, op_weight = dec(getattr(s, S_WEIGHT, None)), dec(getattr(p, P_WEIGHT, None))
    src_cubic, op_cubic = dec(getattr(s, S_CUBIC, None)), dec(getattr(p, P_CUBIC, None))
    pallet = dec(getattr(s, S_PALLET, None))
    src_cp = "" if pallet is None or pallet < 0 else ("C" if pallet == 0 else "P")
    op_cp = txt(getattr(p, P_CP, "")).upper()

    dimensions_diff = not (
        same_num(mm_to_m(src_l_mm), op_l)
        and same_num(mm_to_m(src_w_mm), op_w)
        and same_num(mm_to_m(src_h_mm), op_h)
    )
    weight_diff = not same_num(src_weight, op_weight)
    cubic_diff = not same_num(src_cubic, op_cubic)

    scale = scale_warning((src_l_mm, src_w_mm, src_h_mm), (op_l, op_w, op_h))
    if not scale:
        scale = scale_warning(
            (raw_value(s, "outer_l"), raw_value(s, "outer_w"), raw_value(s, "outer_h")),
            (op_l, op_w, op_h),
        )

    reasons = []
    if txt(getattr(s, S_NAME, "")) != txt(getattr(p, P_NAME, "")):
        reasons.append("NAME_DIFFERENT")
    if txt(getattr(s, S_DESC, "")) != txt(getattr(p, P_DESC, "")):
        reasons.append("DESCRIPTION_DIFFERENT")
    if all(v in (None, Decimal("0")) for v in (src_l_mm, src_w_mm, src_h_mm)):
        reasons.append("SOURCE_DIMENSIONS_ZERO")
    if dimensions_diff:
        reasons.append("DIMENSIONS_DIFFERENT")
    if weight_diff:
        reasons.append("WEIGHT_DIFFERENT")
    if cubic_diff:
        reasons.append("CUBIC_DIFFERENT")
    if src_cp and op_cp and src_cp != op_cp:
        reasons.append("CASE_PALLET_DIFFERENT")
    if scale:
        reasons.append("POSSIBLE_MM_CM_SCALE")

    issues = []
    if not decision:
        status = "UNKNOWN_DRAFT"
        unknown += 1
    else:
        if dimensions_diff and decision.get("dimensions") != "OPERATIONAL":
            issues.append(f"dimensions differ but draft={decision.get('dimensions','MISSING')}")
        if weight_diff and decision.get("weight") != "OPERATIONAL":
            issues.append(f"weight differs but draft={decision.get('weight','MISSING')}")
        if cubic_diff and decision.get("cubic") != "OPERATIONAL":
            issues.append(f"cubic differs but draft={decision.get('cubic','MISSING')}")
        if decision.get("freight_type") == "SOURCE":
            if not src_cp:
                issues.append("freight_type SOURCE but pallet invalid/missing")
            elif op_cp and src_cp != op_cp:
                issues.append(f"freight_type SOURCE would change {op_cp}->{src_cp}")
        if scale and decision.get("dimensions") != "OPERATIONAL":
            issues.append(f"unit-scale warning but dimensions draft={decision.get('dimensions','MISSING')}")

        if issues:
            status = "REVIEW"
            review += 1
        else:
            status = "SAFE_CANDIDATE"
            safe += 1

    blob = json.dumps(payloads, ensure_ascii=False, default=str)
    prev = bool(re.search(r"previous|resolved|approved|repair", blob, re.I))
    identical = bool(re.search(r"identical", blob, re.I))

    rows.append({
        "sku": sku,
        "source_row_number": getattr(s, "source_row_number", ""),
        "reasons": " | ".join(reasons),
        "source_name": txt(getattr(s, S_NAME, "")),
        "operational_name": txt(getattr(p, P_NAME, "")),
        "source_description": txt(getattr(s, S_DESC, "")),
        "operational_description": txt(getattr(p, P_DESC, "")),
        "source_length_mm": src_l_mm,
        "source_width_mm": src_w_mm,
        "source_height_mm": src_h_mm,
        "source_outer_l_mm": dec(raw_value(s, "outer_l")),
        "source_outer_w_mm": dec(raw_value(s, "outer_w")),
        "source_outer_h_mm": dec(raw_value(s, "outer_h")),
        "operational_length_m": op_l,
        "operational_width_m": op_w,
        "operational_height_m": op_h,
        "source_weight_kg": src_weight,
        "operational_weight_kg": op_weight,
        "source_cubic_m3": src_cubic,
        "operational_cubic_m3": op_cubic,
        "source_pallet": pallet,
        "source_derived_cp": src_cp,
        "operational_cp": op_cp,
        "possible_unit_scale_warning": scale,
        "draft_name": decision.get("name", ""),
        "draft_description": decision.get("description", ""),
        "draft_dimensions": decision.get("dimensions", ""),
        "draft_weight": decision.get("weight", ""),
        "draft_cubic": decision.get("cubic", ""),
        "draft_freight_type": decision.get("freight_type", ""),
        "previously_resolved_detected": prev,
        "identical_source_detected": identical,
        "bulk_safety_status": status,
        "bulk_safety_issues": " | ".join(issues),
        "related_draft_memory_payloads_json": blob,
    })

fieldnames = list(rows[0].keys()) if rows else ["sku"]
with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

candidate_models = []
for m in apps.get_models():
    if relevant_model(m):
        candidate_models.append(f"{m._meta.label}: " + ", ".join(f.name for f in m._meta.get_fields()))

DIAG_PATH.write_text("\n".join([
    "WORK.CALC - DRAFT DECISION EXPORT DIAGNOSTICS",
    "=" * 100,
    f"Source file: id={ext.pk} filename={getattr(ext, 'original_filename', '')}",
    f"Operational Products: {len(products)}",
    f"Matched: {len(matched)}",
    f"Operational only: {len(set(products)-set(sources))}",
    "",
    "CANDIDATE RECONCILIATION/MEMORY MODELS",
    "-" * 100,
    *candidate_models,
    "",
    "EXPORT SUMMARY",
    "-" * 100,
    f"Rows exported: {len(rows)}",
    f"Draft decisions parsed: {parsed}",
    f"SAFE_CANDIDATE: {safe}",
    f"REVIEW: {review}",
    f"UNKNOWN_DRAFT: {unknown}",
]), encoding="utf-8")

print("=" * 100)
print("WORK.CALC - DRAFT DECISION EXPORT")
print("=" * 100)
print(f"Source file: ID={ext.pk} / {getattr(ext, 'original_filename', '')}")
print(f"Operational Products: {len(products)}")
print(f"Matched: {len(matched)}")
print(f"Rows exported: {len(rows)}")
print()
print(f"Draft decisions parsed: {parsed}")
print(f"SAFE_CANDIDATE: {safe}")
print(f"REVIEW: {review}")
print(f"UNKNOWN_DRAFT: {unknown}")
print()
print(f"CSV: {CSV_PATH}")
print(f"Diagnostics: {DIAG_PATH}")
print()
print("READ ONLY - NO DATABASE CHANGES MADE")
