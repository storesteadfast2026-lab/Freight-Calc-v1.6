from django.apps import apps
from decimal import Decimal, InvalidOperation
from collections import Counter, defaultdict


TARGET_FILENAME = "products.xls"


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


def same(a, b, tolerance=Decimal("0.000001")):
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


def raw_value(row, *keys):
    raw = getattr(row, "raw_data", None)

    if not isinstance(raw, dict):
        return None

    lowered = {
        str(k).strip().lower(): v
        for k, v in raw.items()
    }

    for key in keys:
        key = key.lower()

        if key in lowered:
            return lowered[key]

    return None


def positive_dimension(value):
    value = dec(value)
    return value is not None and value > 0


Product = find_model("Product")
SourceRow = find_model("ProductSourceRow")

PF = fields(Product)
SF = fields(SourceRow)


# ----------------------------------------------------------
# Field mapping
# ----------------------------------------------------------

P_SKU = first(PF, ["sku", "code", "product_code"])

P_LENGTH = first(PF, ["length_m", "length"])
P_WIDTH = first(PF, ["width_m", "width"])
P_HEIGHT = first(PF, ["height_m", "height"])

P_WEIGHT = first(PF, ["weight_kg", "weight"])
P_CUBIC = first(PF, ["cubic_m3", "cubic"])
P_CP = first(PF, ["freight_type", "type"])

S_SKU = first(
    SF,
    [
        "product_code_normalized",
        "sku_normalized",
        "code_normalized",
        "sku",
        "code",
    ]
)

S_LENGTH = first(SF, ["length_mm", "length"])
S_WIDTH = first(SF, ["width_mm", "width"])
S_HEIGHT = first(SF, ["height_mm", "height"])

S_WEIGHT = first(SF, ["weight_kg", "weight"])
S_CUBIC = first(SF, ["cubic_m3", "cubic"])
S_PALLET = first(SF, ["pallet"])


# ----------------------------------------------------------
# Get newest products.xls
# ----------------------------------------------------------

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

    ExternalFile = SourceRow._meta.get_field(
        relation_field
    ).related_model

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


# ----------------------------------------------------------
# Show RAW DATA keys
# ----------------------------------------------------------

first_row = source_qs.exclude(raw_data=None).first()

print("=" * 100)
print("RAW_DATA STRUCTURE")
print("=" * 100)

if first_row and isinstance(first_row.raw_data, dict):

    print(
        sorted(
            str(k)
            for k in first_row.raw_data.keys()
        )
    )

else:

    print("raw_data is empty or not a dictionary")


# ----------------------------------------------------------
# Build indexes
# ----------------------------------------------------------

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


matched = sorted(
    set(products)
    &
    set(sources)
)


# ----------------------------------------------------------
# Analysis counters
# ----------------------------------------------------------

counts = Counter()

groups = defaultdict(list)


for sku in matched:

    p = products[sku]
    s = sources[sku]

    # Calculator dimensions, metres
    calc_l = dec(
        getattr(p, P_LENGTH, None)
    )

    calc_w = dec(
        getattr(p, P_WIDTH, None)
    )

    calc_h = dec(
        getattr(p, P_HEIGHT, None)
    )


    # Source primary dimensions, mm -> metres
    src_l_mm = dec(
        getattr(s, S_LENGTH, None)
    )

    src_w_mm = dec(
        getattr(s, S_WIDTH, None)
    )

    src_h_mm = dec(
        getattr(s, S_HEIGHT, None)
    )

    src_l = mm_to_m(src_l_mm)
    src_w = mm_to_m(src_w_mm)
    src_h = mm_to_m(src_h_mm)


    # Outer dimensions from raw_data
    outer_l_mm = dec(
        raw_value(
            s,
            "outer_l",
            "outer length",
            "outer_length"
        )
    )

    outer_w_mm = dec(
        raw_value(
            s,
            "outer_w",
            "outer width",
            "outer_width"
        )
    )

    outer_h_mm = dec(
        raw_value(
            s,
            "outer_h",
            "outer height",
            "outer_height"
        )
    )

    outer_l = mm_to_m(outer_l_mm)
    outer_w = mm_to_m(outer_w_mm)
    outer_h = mm_to_m(outer_h_mm)


    # ------------------------------------------------------
    # Primary source dimensional comparison
    # ------------------------------------------------------

    length_diff = not same(calc_l, src_l)
    width_diff = not same(calc_w, src_w)
    height_diff = not same(calc_h, src_h)

    dimension_diff = (
        length_diff
        or width_diff
        or height_diff
    )


    if not dimension_diff:
        counts["PRIMARY_DIMENSIONS_SAME"] += 1
        continue


    counts["DIMENSION_DIFFERENCE"] += 1


    # ------------------------------------------------------
    # Determine whether primary dimensions are effectively zero
    # ------------------------------------------------------

    primary_all_zero = (
        (src_l_mm in (None, Decimal("0")))
        and
        (src_w_mm in (None, Decimal("0")))
        and
        (src_h_mm in (None, Decimal("0")))
    )


    primary_all_positive = (
        positive_dimension(src_l_mm)
        and
        positive_dimension(src_w_mm)
        and
        positive_dimension(src_h_mm)
    )


    outer_complete = (
        positive_dimension(outer_l_mm)
        and
        positive_dimension(outer_w_mm)
        and
        positive_dimension(outer_h_mm)
    )


    outer_matches_calc = (
        outer_complete
        and
        same(calc_l, outer_l)
        and
        same(calc_w, outer_w)
        and
        same(calc_h, outer_h)
    )


    primary_matches_calc = (
        same(calc_l, src_l)
        and
        same(calc_w, src_w)
        and
        same(calc_h, src_h)
    )


    # ------------------------------------------------------
    # Classification
    # ------------------------------------------------------

    if primary_all_zero:

        counts["PRIMARY_ALL_ZERO"] += 1

        if outer_complete:

            counts["PRIMARY_ZERO_OUTER_AVAILABLE"] += 1

            if outer_matches_calc:

                counts[
                    "PRIMARY_ZERO_OUTER_MATCHES_CALCULATOR"
                ] += 1

                group = "PRIMARY ZERO / OUTER MATCHES CALCULATOR"

            else:

                counts[
                    "PRIMARY_ZERO_OUTER_DIFFERS_FROM_CALCULATOR"
                ] += 1

                group = "PRIMARY ZERO / OUTER DIFFERENT"

        else:

            counts[
                "PRIMARY_ZERO_NO_COMPLETE_OUTER"
            ] += 1

            group = "PRIMARY ZERO / NO OUTER"

    elif primary_all_positive:

        counts["PRIMARY_COMPLETE_NONZERO"] += 1

        if outer_complete and outer_matches_calc:

            counts[
                "PRIMARY_DIFFERS_BUT_OUTER_MATCHES_CALCULATOR"
            ] += 1

            group = "PRIMARY DIFFERENT / OUTER MATCHES CALCULATOR"

        else:

            counts[
                "PRIMARY_COMPLETE_AND_DIFFERS"
            ] += 1

            group = "PRIMARY COMPLETE / DIFFERENT"

    else:

        counts["PRIMARY_PARTIAL"] += 1

        if outer_complete and outer_matches_calc:

            counts[
                "PRIMARY_PARTIAL_OUTER_MATCHES_CALCULATOR"
            ] += 1

            group = "PRIMARY PARTIAL / OUTER MATCHES CALCULATOR"

        elif outer_complete:

            counts[
                "PRIMARY_PARTIAL_OUTER_DIFFERS"
            ] += 1

            group = "PRIMARY PARTIAL / OUTER DIFFERENT"

        else:

            group = "PRIMARY PARTIAL / NO OUTER"


    groups[group].append(
        {
            "sku": sku,

            "calc": (
                calc_l,
                calc_w,
                calc_h
            ),

            "primary": (
                src_l,
                src_w,
                src_h
            ),

            "outer": (
                outer_l,
                outer_w,
                outer_h
            ),
        }
    )


# ----------------------------------------------------------
# Summary
# ----------------------------------------------------------

print()
print("=" * 100)
print("DIMENSION ANALYSIS")
print("=" * 100)

print(
    "Matched products:",
    len(matched)
)

print(
    "Primary dimensions same:",
    counts["PRIMARY_DIMENSIONS_SAME"]
)

print(
    "Dimension differences:",
    counts["DIMENSION_DIFFERENCE"]
)

print()

print(
    "Primary all zero:",
    counts["PRIMARY_ALL_ZERO"]
)

print(
    "  -> Outer complete:",
    counts["PRIMARY_ZERO_OUTER_AVAILABLE"]
)

print(
    "  -> Outer matches Calculator:",
    counts["PRIMARY_ZERO_OUTER_MATCHES_CALCULATOR"]
)

print(
    "  -> Outer differs from Calculator:",
    counts["PRIMARY_ZERO_OUTER_DIFFERS_FROM_CALCULATOR"]
)

print(
    "  -> No complete Outer:",
    counts["PRIMARY_ZERO_NO_COMPLETE_OUTER"]
)

print()

print(
    "Primary complete/non-zero:",
    counts["PRIMARY_COMPLETE_NONZERO"]
)

print(
    "  -> Differs but Outer matches Calculator:",
    counts["PRIMARY_DIFFERS_BUT_OUTER_MATCHES_CALCULATOR"]
)

print(
    "  -> Primary different:",
    counts["PRIMARY_COMPLETE_AND_DIFFERS"]
)

print()

print(
    "Primary partial:",
    counts["PRIMARY_PARTIAL"]
)

print(
    "  -> Outer matches Calculator:",
    counts["PRIMARY_PARTIAL_OUTER_MATCHES_CALCULATOR"]
)

print(
    "  -> Outer different:",
    counts["PRIMARY_PARTIAL_OUTER_DIFFERS"]
)


# ----------------------------------------------------------
# Groups
# ----------------------------------------------------------

print()
print("=" * 100)
print("GROUP DETAILS")
print("=" * 100)


for group_name, rows in sorted(
    groups.items(),
    key=lambda item: -len(item[1])
):

    print()

    print(
        f"{len(rows):>4}  {group_name}"
    )

    for row in rows[:10]:

        print(
            "      ",
            row["sku"],
            "| Calc:",
            row["calc"],
            "| Primary:",
            row["primary"],
            "| Outer:",
            row["outer"],
        )


print()
print("=" * 100)
print("READ ONLY - NO DATABASE CHANGES MADE")
print("=" * 100)