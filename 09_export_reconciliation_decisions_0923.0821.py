# Work.Calc / Freight Calculator
# SCRIPT 09 - READ ONLY
#
# Corrected exporter:
# Reads ProductReconciliationDecision DIRECTLY instead of trying to reach it
# through ProductSourceRow relations.
#
# Outputs:
#   /tmp/reconciliation_decisions_0923.0821.csv
#   /tmp/reconciliation_decisions_summary_0923.0821.txt
#
# NO database changes are made.

from django.apps import apps
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections import Counter
import csv
import json

TARGET_FILENAME = "products.xls"
CSV_PATH = Path("/tmp/reconciliation_decisions_0923.0821.csv")
SUMMARY_PATH = Path("/tmp/reconciliation_decisions_summary_0923.0821.txt")


def find_model(name):
    matches = [m for m in apps.get_models() if m.__name__ == name]
    if not matches:
        raise RuntimeError(f"Model not found: {name}")
    return matches[0]


def fields(model):
    return {
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "concrete", False)
    }


def first(existing, candidates):
    for c in candidates:
        if c in existing:
            return c
    return None


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


def raw_value(row, *keys):
    raw = getattr(row, "raw_data", None)
    if not isinstance(raw, dict):
        return None
    lower = {str(k).strip().lower(): v for k, v in raw.items()}
    for key in keys:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def parse_jsonish(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                return json.loads(s)
            except Exception:
                return {}
    return {}


def norm_decisions(v):
    data = parse_jsonish(v)
    result = {}
    for key in (
        "name",
        "description",
        "dimensions",
        "weight",
        "cubic",
        "freight_type",
    ):
        value = txt(data.get(key, "")).upper()
        if value:
            result[key] = value
    return result


def scale_relation(values_mm, op_values_m):
    op_mm = [m_to_mm(x) for x in op_values_m]
    ratios = []
    for value, ref in zip(values_mm, op_mm):
        value, ref = dec(value), dec(ref)
        if value is None or ref is None or value <= 0 or ref <= 0:
            continue
        ratios.append(value / ref)

    if len(ratios) >= 2:
        x10 = sum(Decimal("8.5") <= r <= Decimal("11.5") for r in ratios)
        x01 = sum(Decimal("0.085") <= r <= Decimal("0.115") for r in ratios)
        if x10 >= 2:
            return "TL_APPROX_10X_OPERATIONAL"
        if x01 >= 2:
            return "TL_APPROX_0.1X_OPERATIONAL"
    return ""


Product = find_model("Product")
SourceRow = find_model("ProductSourceRow")
Decision = find_model("ProductReconciliationDecision")
Rule = find_model("ProductReconciliationRule")
Memory = find_model("ExternalDataCorrectionMemory")

PF = fields(Product)
SF = fields(SourceRow)

P_SKU = first(PF, ["sku", "code", "product_code"])
P_NAME = first(PF, ["name", "product_name"])
P_DESC = first(PF, ["description", "desc"])
P_LENGTH = first(PF, ["length_m", "length"])
P_WIDTH = first(PF, ["width_m", "width"])
P_HEIGHT = first(PF, ["height_m", "height"])
P_WEIGHT = first(PF, ["weight_kg", "weight"])
P_CUBIC = first(PF, ["cubic_m3", "cubic"])
P_CP = first(PF, ["freight_type", "type"])

S_SKU = first(SF, [
    "product_code_normalized",
    "sku_normalized",
    "code_normalized",
    "sku",
    "code",
    "product_code",
])
S_NAME = first(SF, ["name", "product_name"])
S_DESC = first(SF, ["description", "desc"])
S_LENGTH = first(SF, ["length_mm", "length"])
S_WIDTH = first(SF, ["width_mm", "width"])
S_HEIGHT = first(SF, ["height_mm", "height"])
S_WEIGHT = first(SF, ["weight_kg", "weight"])
S_CUBIC = first(SF, ["cubic_m3", "cubic"])
S_PALLET = first(SF, ["pallet"])

# Locate current products.xls ExternalDataFile via SourceRow relation.
relation_field = None
for f in SourceRow._meta.get_fields():
    if not getattr(f, "many_to_one", False):
        continue
    related = getattr(f, "related_model", None)
    if related and "original_filename" in fields(related):
        relation_field = f.name
        break

if not relation_field:
    raise RuntimeError("Could not locate ProductSourceRow -> ExternalDataFile relation.")

ExternalFile = SourceRow._meta.get_field(relation_field).related_model
external_file = (
    ExternalFile.objects
    .filter(original_filename__iexact=TARGET_FILENAME)
    .order_by("-pk")
    .first()
)

if not external_file:
    raise RuntimeError(f"No {TARGET_FILENAME} ExternalDataFile found.")

source_qs = SourceRow.objects.filter(**{relation_field: external_file})
decision_qs = Decision.objects.filter(external_file=external_file)

# Build indexes
sources = {}
for s in source_qs.iterator():
    sku = txt(getattr(s, S_SKU, ""))
    if sku:
        sources[sku] = s

products = {}
for p in Product.objects.all():
    sku = txt(getattr(p, P_SKU, ""))
    if sku:
        products[sku] = p

decisions = {}
duplicate_decisions = []
for d in decision_qs.order_by("pk"):
    sku = txt(getattr(d, "product_code_normalized", ""))
    if not sku:
        continue
    if sku in decisions:
        duplicate_decisions.append(sku)
    decisions[sku] = d

matched = sorted(set(products) & set(sources))

# Active reusable rules keyed by group_key
rules_by_group = {}
for r in Rule.objects.filter(active=True):
    key = txt(getattr(r, "group_key", ""))
    if key:
        rules_by_group.setdefault(key, []).append(r)

# Active correction memory by record_key.
memory_by_key = {}
for m in Memory.objects.filter(is_active=True).order_by("-approved_at", "-pk"):
    key = txt(getattr(m, "record_key", ""))
    if key and key not in memory_by_key:
        memory_by_key[key] = m

rows = []
status_counts = Counter()
decision_status_counts = Counter()
group_counts = Counter()
decision_signature_counts = Counter()

for sku in matched:
    p = products[sku]
    s = sources[sku]
    d = decisions.get(sku)

    src_l_mm = dec(getattr(s, S_LENGTH, None)) if S_LENGTH else None
    src_w_mm = dec(getattr(s, S_WIDTH, None)) if S_WIDTH else None
    src_h_mm = dec(getattr(s, S_HEIGHT, None)) if S_HEIGHT else None

    src_outer_l_mm = dec(raw_value(s, "outer_l"))
    src_outer_w_mm = dec(raw_value(s, "outer_w"))
    src_outer_h_mm = dec(raw_value(s, "outer_h"))

    op_l_m = dec(getattr(p, P_LENGTH, None)) if P_LENGTH else None
    op_w_m = dec(getattr(p, P_WIDTH, None)) if P_WIDTH else None
    op_h_m = dec(getattr(p, P_HEIGHT, None)) if P_HEIGHT else None

    src_weight = dec(getattr(s, S_WEIGHT, None)) if S_WEIGHT else None
    op_weight = dec(getattr(p, P_WEIGHT, None)) if P_WEIGHT else None

    src_cubic = dec(getattr(s, S_CUBIC, None)) if S_CUBIC else None
    op_cubic = dec(getattr(p, P_CUBIC, None)) if P_CUBIC else None

    pallet = dec(getattr(s, S_PALLET, None)) if S_PALLET else None
    src_cp = ""
    if pallet is not None and pallet >= 0:
        src_cp = "C" if pallet == 0 else "P"

    op_cp = txt(getattr(p, P_CP, "")).upper() if P_CP else ""

    primary_dim_diff = not (
        same_num(mm_to_m(src_l_mm), op_l_m)
        and same_num(mm_to_m(src_w_mm), op_w_m)
        and same_num(mm_to_m(src_h_mm), op_h_m)
    )

    weight_diff = not same_num(src_weight, op_weight)
    cubic_diff = not same_num(src_cubic, op_cubic)
    cp_diff = bool(src_cp and op_cp and src_cp != op_cp)

    unit_warning = scale_relation(
        [src_l_mm, src_w_mm, src_h_mm],
        [op_l_m, op_w_m, op_h_m],
    )
    if not unit_warning:
        unit_warning = scale_relation(
            [src_outer_l_mm, src_outer_w_mm, src_outer_h_mm],
            [op_l_m, op_w_m, op_h_m],
        )

    fd = norm_decisions(getattr(d, "field_decisions", None)) if d else {}

    draft_name = fd.get("name", "")
    draft_desc = fd.get("description", "")
    draft_dims = fd.get("dimensions", "")
    draft_weight = fd.get("weight", "")
    draft_cubic = fd.get("cubic", "")
    draft_cp = fd.get("freight_type", "")

    safety_issues = []

    if not d:
        safety_status = "NO_DECISION_RECORD"
    else:
        # Conservative safety rules for a BULK APPLY:
        # If current operational physical values differ from source, draft must protect them.
        if primary_dim_diff and draft_dims != "OPERATIONAL":
            safety_issues.append(
                f"dimensions differ; draft={draft_dims or 'MISSING'}"
            )

        if weight_diff and draft_weight != "OPERATIONAL":
            safety_issues.append(
                f"weight differs; draft={draft_weight or 'MISSING'}"
            )

        if cubic_diff and draft_cubic != "OPERATIONAL":
            safety_issues.append(
                f"cubic differs; draft={draft_cubic or 'MISSING'}"
            )

        if unit_warning and draft_dims != "OPERATIONAL":
            safety_issues.append(
                f"{unit_warning}; dimensions draft={draft_dims or 'MISSING'}"
            )

        if draft_cp == "SOURCE":
            if not src_cp:
                safety_issues.append("freight_type SOURCE but source pallet invalid")
            elif op_cp and src_cp != op_cp:
                safety_issues.append(
                    f"freight_type SOURCE would change {op_cp}->{src_cp}"
                )

        # A missing field decision is also unsafe if that field currently differs.
        if safety_issues:
            safety_status = "REVIEW"
        else:
            safety_status = "SAFE_CANDIDATE"

    status_counts[safety_status] += 1

    decision_status = txt(getattr(d, "decision_status", "")) if d else ""
    decision_status_counts[decision_status or "<NONE>"] += 1

    group_key = txt(getattr(d, "group_key", "")) if d else ""
    group_counts[group_key or "<NONE>"] += 1

    signature = (
        draft_name,
        draft_desc,
        draft_dims,
        draft_weight,
        draft_cubic,
        draft_cp,
    )
    decision_signature_counts[signature] += 1

    rule_list = rules_by_group.get(group_key, [])
    rule_names = [txt(getattr(r, "name", "")) for r in rule_list]
    rule_decisions = [
        parse_jsonish(getattr(r, "field_decisions", None))
        for r in rule_list
    ]

    memory = memory_by_key.get(sku)
    memory_exists = memory is not None

    row = {
        "sku": sku,
        "source_row_number": getattr(s, "source_row_number", ""),

        "row_status": txt(getattr(d, "row_status", "")) if d else "",
        "group_key": group_key,
        "row_action": txt(getattr(d, "row_action", "")) if d else "",
        "decision_status": decision_status,

        "draft_name": draft_name,
        "draft_description": draft_desc,
        "draft_dimensions": draft_dims,
        "draft_weight": draft_weight,
        "draft_cubic": draft_cubic,
        "draft_freight_type": draft_cp,

        "field_decisions_json": json.dumps(
            parse_jsonish(getattr(d, "field_decisions", None)) if d else {},
            ensure_ascii=False,
            default=str,
        ),
        "custom_values_json": json.dumps(
            parse_jsonish(getattr(d, "custom_values", None)) if d else {},
            ensure_ascii=False,
            default=str,
        ),

        "notes": txt(getattr(d, "notes", "")) if d else "",
        "reviewed_by_id": getattr(d, "reviewed_by_id", "") if d else "",
        "reviewed_at": getattr(d, "reviewed_at", "") if d else "",
        "applied_by_id": getattr(d, "applied_by_id", "") if d else "",
        "applied_at": getattr(d, "applied_at", "") if d else "",
        "apply_batch_id": txt(getattr(d, "apply_batch_id", "")) if d else "",

        "source_name": txt(getattr(s, S_NAME, "")) if S_NAME else "",
        "operational_name": txt(getattr(p, P_NAME, "")) if P_NAME else "",
        "source_description": txt(getattr(s, S_DESC, "")) if S_DESC else "",
        "operational_description": txt(getattr(p, P_DESC, "")) if P_DESC else "",

        "source_length_mm": src_l_mm,
        "source_width_mm": src_w_mm,
        "source_height_mm": src_h_mm,
        "source_outer_l_mm": src_outer_l_mm,
        "source_outer_w_mm": src_outer_w_mm,
        "source_outer_h_mm": src_outer_h_mm,

        "operational_length_m": op_l_m,
        "operational_width_m": op_w_m,
        "operational_height_m": op_h_m,

        "source_weight_kg": src_weight,
        "operational_weight_kg": op_weight,
        "source_cubic_m3": src_cubic,
        "operational_cubic_m3": op_cubic,

        "source_pallet": pallet,
        "source_derived_cp": src_cp,
        "operational_cp": op_cp,

        "primary_dimensions_different": primary_dim_diff,
        "weight_different": weight_diff,
        "cubic_different": cubic_diff,
        "cp_different": cp_diff,
        "possible_unit_scale_warning": unit_warning,

        "active_rule_count": len(rule_list),
        "active_rule_names": " | ".join(rule_names),
        "active_rule_decisions_json": json.dumps(
            rule_decisions,
            ensure_ascii=False,
            default=str,
        ),

        "active_memory_exists": memory_exists,
        "memory_workflow_key": txt(getattr(memory, "workflow_key", "")) if memory else "",
        "memory_source_fingerprint": txt(getattr(memory, "source_fingerprint", "")) if memory else "",
        "memory_proposal_fingerprint": txt(getattr(memory, "proposal_fingerprint", "")) if memory else "",
        "memory_approved_data_json": json.dumps(
            getattr(memory, "approved_data", {}) if memory else {},
            ensure_ascii=False,
            default=str,
        ),
        "memory_approval_note": txt(getattr(memory, "approval_note", "")) if memory else "",
        "memory_approved_at": getattr(memory, "approved_at", "") if memory else "",
        "memory_last_used_at": getattr(memory, "last_used_at", "") if memory else "",
        "memory_use_count": getattr(memory, "use_count", "") if memory else "",

        "bulk_safety_status": safety_status,
        "bulk_safety_issues": " | ".join(safety_issues),
    }

    rows.append(row)

# Write CSV
fieldnames = list(rows[0].keys()) if rows else ["sku"]
with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

# Summary
lines = []
lines.append("WORK.CALC - RECONCILIATION DECISION EXPORT SUMMARY")
lines.append("=" * 100)
lines.append(f"Source file: ID={external_file.pk} / {external_file.original_filename}")
lines.append(f"Operational Products: {len(products)}")
lines.append(f"Source rows: {source_qs.count()}")
lines.append(f"Matched Products: {len(matched)}")
lines.append(f"Decision records for source file: {decision_qs.count()}")
lines.append(f"Decision SKUs indexed: {len(decisions)}")
lines.append(f"Duplicate decision SKUs encountered: {len(duplicate_decisions)}")
lines.append("")
lines.append("BULK SAFETY")
lines.append("-" * 100)
for k, v in status_counts.most_common():
    lines.append(f"{k}: {v}")

lines.append("")
lines.append("DECISION STATUS")
lines.append("-" * 100)
for k, v in decision_status_counts.most_common():
    lines.append(f"{k}: {v}")

lines.append("")
lines.append("GROUP KEYS")
lines.append("-" * 100)
for k, v in group_counts.most_common():
    lines.append(f"{v:>4}  {k}")

lines.append("")
lines.append("DRAFT DECISION SIGNATURES")
lines.append("-" * 100)
for sig, count in decision_signature_counts.most_common():
    lines.append(
        f"{count:>4}  "
        f"name={sig[0] or '-'}; "
        f"description={sig[1] or '-'}; "
        f"dimensions={sig[2] or '-'}; "
        f"weight={sig[3] or '-'}; "
        f"cubic={sig[4] or '-'}; "
        f"freight_type={sig[5] or '-'}"
    )

review_rows = [r for r in rows if r["bulk_safety_status"] == "REVIEW"]
lines.append("")
lines.append("REVIEW SKUS")
lines.append("-" * 100)
if review_rows:
    for r in review_rows:
        lines.append(f"{r['sku']}: {r['bulk_safety_issues']}")
else:
    lines.append("None")

no_decision = [r for r in rows if r["bulk_safety_status"] == "NO_DECISION_RECORD"]
lines.append("")
lines.append("NO DECISION RECORD SKUS")
lines.append("-" * 100)
if no_decision:
    for r in no_decision:
        lines.append(r["sku"])
else:
    lines.append("None")

SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")

print("=" * 100)
print("WORK.CALC - CORRECTED RECONCILIATION DECISION EXPORT")
print("=" * 100)
print(f"Source: ID={external_file.pk} / {external_file.original_filename}")
print(f"Matched Products: {len(matched)}")
print(f"Decision records for source file: {decision_qs.count()}")
print(f"Decision SKUs indexed: {len(decisions)}")
print()
for k, v in status_counts.most_common():
    print(f"{k}: {v}")
print()
print(f"CSV: {CSV_PATH}")
print(f"Summary: {SUMMARY_PATH}")
print()
print("READ ONLY - NO DATABASE CHANGES MADE")
