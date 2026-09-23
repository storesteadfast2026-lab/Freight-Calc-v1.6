# Work.Calc / Freight Calculator
# Script 05 - READ ONLY
# Validates Weight, Cubic and possible mm/cm scale issues.
# Makes NO database changes.

from django.apps import apps
from decimal import Decimal, InvalidOperation
from collections import Counter, defaultdict

TARGET_FILENAME = "products.xls"
RATIO_TOL = Decimal("0.15")   # +/-15% around x10 or x0.1 for unit-scale warning
CUBIC_REL_TOL = Decimal("0.05")  # 5% informational warning only


def find_model(name):
    for model in apps.get_models():
        if model.__name__ == name:
            return model
    raise RuntimeError(f"Model not found: {name}")


def fields(model):
    return {
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "concrete", False)
    }


def first(existing, candidates):
    for name in candidates:
        if name in existing:
            return name
    return None


def txt(value):
    if value is None:
        return ""
    return str(value).strip()


def dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def same_num(a, b, tolerance=Decimal("0.000001")):
    a = dec(a)
    b = dec(b)

    if a is None and b is None:
        return True
    if a is None or b is None:
        return False

    return abs(a - b) <= tolerance


def mm_to_m(value):
    value = dec(value)
    if value is None:
        return None
    return value / Decimal("1000")


def m_to_mm(value):
    value = dec(value)
    if value is None:
        return None
    return value * Decimal("1000")


def raw_value(row, *keys):
    raw = getattr(row, "raw_data", None)

    if not isinstance(raw, dict):
        return None

    lowered = {
        str(k).strip().lower(): v
        for k, v in raw.items()
    }

    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]

    return None


def positive(value):
    value = dec(value)
    return value is not None and value > 0


def ratio_near(value, target, tolerance=RATIO_TOL):
    value = dec(value)
    target = dec(target)

    if value is None or target is None or target == 0:
        return False

    ratio = value / target

    return abs(ratio - Decimal("10")) <= Decimal("10") * tolerance


def ratio_near_tenth(value, target, tolerance=RATIO_TOL):
    value = dec(value)
    target = dec(target)

    if value is None or target is None or target == 0:
        return False

    ratio = value / target

    return abs(ratio - Decimal("0.1")) <= Decimal("0.1") * tolerance


def rel_diff(a, b):
    a = dec(a)
    b = dec(b)

    if a is None or b is None:
        return None

    denom = max(abs(a), abs(b), Decimal("0.0000001"))
    return abs(a - b) / denom


Product = find_model("Product")
SourceRow = find_model("ProductSourceRow")

PF = fields(Product)
SF = fields(SourceRow)

# Product fields
P_SKU = first(PF, ["sku", "code", "product_code"])
P_WEIGHT = first(PF, ["weight_kg", "weight"])
P_CUBIC = first(PF, ["cubic_m3", "cubic"])
P_LENGTH = first(PF, ["length_m", "length"])
P_WIDTH = first(PF, ["width_m", "width"])
P_HEIGHT = first(PF, ["height_m", "height"])
P_CP = first(PF, ["freight_type", "type"])

# Source fields
S_SKU = first(
    SF,
    [
        "product_code_normalized",
        "sku_normalized",
        "code_normalized",
        "sku",
        "code",
        "product_code",
    ],
)
S_WEIGHT = first(SF, ["weight_kg", "weight"])
S_CUBIC = first(SF, ["cubic_m3", "cubic"])
S_LENGTH = first(SF, ["length_mm", "length"])
S_WIDTH = first(SF, ["width_mm", "width"])
S_HEIGHT = first(SF, ["height_mm", "height"])
S_PALLET = first(SF, ["pallet"])

# Isolate latest products.xls
relation_field = None

for f in SourceRow._meta.get_fields():
    if not getattr(f, "many_to_one", False):
        continue

    related = getattr(f, "related_model", None)
    if related and "original_filename" in fields(related):
        relation_field = f.name
        break

source_qs = SourceRow.objects.all()
selected_file = None

if relation_field:
    ExternalFile = SourceRow._meta.get_field(relation_field).related_model

    selected_file = (
        ExternalFile.objects
        .filter(original_filename__iexact=TARGET_FILENAME)
        .order_by("-pk")
        .first()
    )

    if selected_file:
        source_qs = source_qs.filter(
            **{relation_field: selected_file}
        )

products = {}
for p in Product.objects.all():
    sku = txt(getattr(p, P_SKU, ""))
    if sku:
        products[sku] = p

sources = {}
for s in source_qs.iterator():
    sku = txt(getattr(s, S_SKU, ""))
    if sku:
        sources[sku] = s

matched = sorted(set(products) & set(sources))

counts = Counter()
examples = defaultdict(list)
review_skus = set()
unit_warning_skus = set()

def add_example(key, item, limit=12):
    if len(examples[key]) < limit:
        examples[key].append(item)


for sku in matched:
    p = products[sku]
    s = sources[sku]

    calc_weight = dec(getattr(p, P_WEIGHT, None))
    src_weight = dec(getattr(s, S_WEIGHT, None))

    calc_cubic = dec(getattr(p, P_CUBIC, None))
    src_cubic = dec(getattr(s, S_CUBIC, None))

    calc_l_m = dec(getattr(p, P_LENGTH, None))
    calc_w_m = dec(getattr(p, P_WIDTH, None))
    calc_h_m = dec(getattr(p, P_HEIGHT, None))

    calc_l_mm = m_to_mm(calc_l_m)
    calc_w_mm = m_to_mm(calc_w_m)
    calc_h_mm = m_to_mm(calc_h_m)

    src_l_mm = dec(getattr(s, S_LENGTH, None))
    src_w_mm = dec(getattr(s, S_WIDTH, None))
    src_h_mm = dec(getattr(s, S_HEIGHT, None))

    outer_l_mm = dec(raw_value(s, "outer_l", "outer length", "outer_length"))
    outer_w_mm = dec(raw_value(s, "outer_w", "outer width", "outer_width"))
    outer_h_mm = dec(raw_value(s, "outer_h", "outer height", "outer_height"))

    # ------------------------------------------------------
    # WEIGHT
    # ------------------------------------------------------
    if same_num(calc_weight, src_weight):
        counts["WEIGHT_SAME"] += 1
    else:
        counts["WEIGHT_DIFFERENT"] += 1
        review_skus.add(sku)

        if (src_weight is None or src_weight == 0) and positive(calc_weight):
            counts["WEIGHT_SOURCE_ZERO"] += 1
            add_example(
                "WEIGHT_SOURCE_ZERO",
                (sku, calc_weight, src_weight)
            )

        elif (calc_weight is None or calc_weight == 0) and positive(src_weight):
            counts["WEIGHT_CALC_ZERO"] += 1
            add_example(
                "WEIGHT_CALC_ZERO",
                (sku, calc_weight, src_weight)
            )

        elif positive(calc_weight) and positive(src_weight):
            counts["WEIGHT_BOTH_POSITIVE_DIFFERENT"] += 1
            add_example(
                "WEIGHT_BOTH_POSITIVE_DIFFERENT",
                (sku, calc_weight, src_weight)
            )

        else:
            counts["WEIGHT_OTHER"] += 1
            add_example(
                "WEIGHT_OTHER",
                (sku, calc_weight, src_weight)
            )

    # ------------------------------------------------------
    # CUBIC
    # ------------------------------------------------------
    if same_num(calc_cubic, src_cubic):
        counts["CUBIC_SAME"] += 1
    else:
        counts["CUBIC_DIFFERENT"] += 1
        review_skus.add(sku)

        if (src_cubic is None or src_cubic == 0) and positive(calc_cubic):
            counts["CUBIC_SOURCE_ZERO"] += 1
            add_example(
                "CUBIC_SOURCE_ZERO",
                (sku, calc_cubic, src_cubic)
            )

        elif (calc_cubic is None or calc_cubic == 0) and positive(src_cubic):
            counts["CUBIC_CALC_ZERO"] += 1
            add_example(
                "CUBIC_CALC_ZERO",
                (sku, calc_cubic, src_cubic)
            )

        elif positive(calc_cubic) and positive(src_cubic):
            counts["CUBIC_BOTH_POSITIVE_DIFFERENT"] += 1
            add_example(
                "CUBIC_BOTH_POSITIVE_DIFFERENT",
                (sku, calc_cubic, src_cubic)
            )

        else:
            counts["CUBIC_OTHER"] += 1
            add_example(
                "CUBIC_OTHER",
                (sku, calc_cubic, src_cubic)
            )

    # ------------------------------------------------------
    # Determine effective TL dimensions for informational
    # cubic check. Primary first if complete/non-zero,
    # otherwise Outer.
    # ------------------------------------------------------
    primary_complete = (
        positive(src_l_mm) and
        positive(src_w_mm) and
        positive(src_h_mm)
    )

    outer_complete = (
        positive(outer_l_mm) and
        positive(outer_w_mm) and
        positive(outer_h_mm)
    )

    effective_dims_name = None
    eff_l_mm = eff_w_mm = eff_h_mm = None

    if primary_complete:
        effective_dims_name = "PRIMARY"
        eff_l_mm, eff_w_mm, eff_h_mm = (
            src_l_mm, src_w_mm, src_h_mm
        )
    elif outer_complete:
        effective_dims_name = "OUTER"
        eff_l_mm, eff_w_mm, eff_h_mm = (
            outer_l_mm, outer_w_mm, outer_h_mm
        )

    if effective_dims_name and positive(src_cubic):
        derived_cubic = (
            (eff_l_mm / Decimal("1000")) *
            (eff_w_mm / Decimal("1000")) *
            (eff_h_mm / Decimal("1000"))
        )

        difference = rel_diff(src_cubic, derived_cubic)

        if difference is not None and difference > CUBIC_REL_TOL:
            counts["SOURCE_CUBIC_VS_DIM_WARNING"] += 1
            add_example(
                "SOURCE_CUBIC_VS_DIM_WARNING",
                (
                    sku,
                    effective_dims_name,
                    src_cubic,
                    derived_cubic,
                    difference
                )
            )

    # ------------------------------------------------------
    # POSSIBLE MM / CM SCALE WARNING
    #
    # TL source dimensions are expected to be in mm.
    # We compare raw TL mm values against Calculator
    # converted to mm. If at least 2 dimensions are
    # approximately x10 or x0.1, flag for manual review.
    # No automatic conversion is performed.
    # ------------------------------------------------------
    def scale_pattern(values_mm, ref_mm):
        ratios_x10 = 0
        ratios_x01 = 0
        compared = 0

        for value, ref in zip(values_mm, ref_mm):
            if not positive(value) or not positive(ref):
                continue

            compared += 1

            if ratio_near(value, ref):
                ratios_x10 += 1

            if ratio_near_tenth(value, ref):
                ratios_x01 += 1

        if compared >= 2 and ratios_x10 >= 2:
            return "TL approximately 10x Calculator"

        if compared >= 2 and ratios_x01 >= 2:
            return "TL approximately 0.1x Calculator"

        return None

    calc_mm = (calc_l_mm, calc_w_mm, calc_h_mm)

    primary_pattern = scale_pattern(
        (src_l_mm, src_w_mm, src_h_mm),
        calc_mm
    )

    outer_pattern = scale_pattern(
        (outer_l_mm, outer_w_mm, outer_h_mm),
        calc_mm
    )

    if primary_pattern:
        counts["UNIT_WARNING_PRIMARY"] += 1
        unit_warning_skus.add(sku)
        review_skus.add(sku)

        add_example(
            "UNIT_WARNING_PRIMARY",
            (
                sku,
                primary_pattern,
                calc_mm,
                (src_l_mm, src_w_mm, src_h_mm)
            )
        )

    if outer_pattern:
        counts["UNIT_WARNING_OUTER"] += 1
        unit_warning_skus.add(sku)
        review_skus.add(sku)

        add_example(
            "UNIT_WARNING_OUTER",
            (
                sku,
                outer_pattern,
                calc_mm,
                (outer_l_mm, outer_w_mm, outer_h_mm)
            )
        )

    # ------------------------------------------------------
    # C/P conflict - include in final review union
    # ------------------------------------------------------
    calc_cp = txt(getattr(p, P_CP, "")).upper()
    pallet = dec(getattr(s, S_PALLET, None))

    if pallet is None or pallet < 0:
        counts["PALLET_INVALID"] += 1
        review_skus.add(sku)
    else:
        src_cp = "C" if pallet == 0 else "P"

        if calc_cp and src_cp != calc_cp:
            counts["CP_DIFFERENT"] += 1
            review_skus.add(sku)
            add_example(
                "CP_DIFFERENT",
                (sku, calc_cp, src_cp, pallet)
            )


print("=" * 100)
print("WORK.CALC - WEIGHT / CUBIC / UNIT VALIDATION")
print("=" * 100)

if selected_file:
    print(f"Source file: {selected_file.pk} / {getattr(selected_file, 'original_filename', '')}")

print(f"Matched products: {len(matched)}")
print()

print("=" * 100)
print("WEIGHT")
print("=" * 100)
print("Same:", counts["WEIGHT_SAME"])
print("Different:", counts["WEIGHT_DIFFERENT"])
print("  Source zero / Calculator > 0:", counts["WEIGHT_SOURCE_ZERO"])
print("  Calculator zero / Source > 0:", counts["WEIGHT_CALC_ZERO"])
print("  Both > 0 but different:", counts["WEIGHT_BOTH_POSITIVE_DIFFERENT"])
print("  Other:", counts["WEIGHT_OTHER"])

print()
print("=" * 100)
print("CUBIC")
print("=" * 100)
print("Same:", counts["CUBIC_SAME"])
print("Different:", counts["CUBIC_DIFFERENT"])
print("  Source zero / Calculator > 0:", counts["CUBIC_SOURCE_ZERO"])
print("  Calculator zero / Source > 0:", counts["CUBIC_CALC_ZERO"])
print("  Both > 0 but different:", counts["CUBIC_BOTH_POSITIVE_DIFFERENT"])
print("  Other:", counts["CUBIC_OTHER"])
print()
print(
    "Informational warning - Source cubic differs >5% from "
    "cubic calculated from effective TL dimensions:",
    counts["SOURCE_CUBIC_VS_DIM_WARNING"]
)

print()
print("=" * 100)
print("POSSIBLE MM / CM UNIT-SCALE WARNINGS")
print("=" * 100)
print("Primary-dimension warnings:", counts["UNIT_WARNING_PRIMARY"])
print("Outer-dimension warnings:", counts["UNIT_WARNING_OUTER"])
print("Unique SKUs with unit warning:", len(unit_warning_skus))
print()
print(
    "Rule: TL dimensions are expected in mm. "
    "x10 / x0.1 patterns are WARNINGS only; no automatic conversion."
)

print()
print("=" * 100)
print("CASE / PALLET")
print("=" * 100)
print("C/P different:", counts["CP_DIFFERENT"])
print("Invalid/missing pallet:", counts["PALLET_INVALID"])

print()
print("=" * 100)
print("REVIEW UNION")
print("=" * 100)
print(
    "Unique matched SKUs with at least one Weight/Cubic/C-P/"
    "unit-scale review condition:",
    len(review_skus)
)
print("Review SKUs:")
print(", ".join(sorted(review_skus)) if review_skus else "None")

def print_examples(title, key):
    rows = examples.get(key, [])
    print()
    print("-" * 100)
    print(title)
    print("-" * 100)

    if not rows:
        print("None")
        return

    for row in rows:
        print(row)

print_examples(
    "WEIGHT - SOURCE ZERO / CALCULATOR > 0",
    "WEIGHT_SOURCE_ZERO"
)
print_examples(
    "WEIGHT - BOTH POSITIVE BUT DIFFERENT",
    "WEIGHT_BOTH_POSITIVE_DIFFERENT"
)
print_examples(
    "CUBIC - SOURCE ZERO / CALCULATOR > 0",
    "CUBIC_SOURCE_ZERO"
)
print_examples(
    "CUBIC - BOTH POSITIVE BUT DIFFERENT",
    "CUBIC_BOTH_POSITIVE_DIFFERENT"
)
print_examples(
    "SOURCE CUBIC VS EFFECTIVE TL DIMENSIONS (>5%)",
    "SOURCE_CUBIC_VS_DIM_WARNING"
)
print_examples(
    "POSSIBLE MM/CM WARNING - PRIMARY",
    "UNIT_WARNING_PRIMARY"
)
print_examples(
    "POSSIBLE MM/CM WARNING - OUTER",
    "UNIT_WARNING_OUTER"
)
print_examples(
    "C/P DIFFERENCES",
    "CP_DIFFERENT"
)

print()
print("=" * 100)
print("READ ONLY - NO DATABASE CHANGES MADE")
print("=" * 100)
