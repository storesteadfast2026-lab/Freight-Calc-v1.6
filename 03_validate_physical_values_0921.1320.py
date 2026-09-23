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


def txt(v):
    if v is None:
        return ""
    return str(v).strip()


def dec(v):
    if v in (None, ""):
        return None

    try:
        return Decimal(str(v))
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


def source_dimension_to_metres(value, field_name):

    value = dec(value)

    if value is None:
        return None

    if field_name and field_name.endswith("_mm"):
        return value / Decimal("1000")

    return value


Product = find_model("Product")
SourceRow = find_model("ProductSourceRow")

PF = fields(Product)
SF = fields(SourceRow)


# Calculator
P_SKU = first(PF, ["sku", "code", "product_code"])

P_NAME = first(PF, ["name"])
P_DESC = first(PF, ["description"])

P_LENGTH = first(PF, ["length_m", "length", "length_mm"])
P_WIDTH = first(PF, ["width_m", "width", "width_mm"])
P_HEIGHT = first(PF, ["height_m", "height", "height_mm"])

P_WEIGHT = first(PF, ["weight_kg", "weight"])
P_CUBIC = first(PF, ["cubic_m3", "cubic"])
P_CP = first(PF, ["freight_type", "type"])


# Source
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

S_NAME = first(SF, ["name"])
S_DESC = first(SF, ["description"])

S_LENGTH = first(SF, ["length_mm", "length_m", "length"])
S_WIDTH = first(SF, ["width_mm", "width_m", "width"])
S_HEIGHT = first(SF, ["height_mm", "height_m", "height"])

S_WEIGHT = first(SF, ["weight_kg", "weight"])
S_CUBIC = first(SF, ["cubic_m3", "cubic"])
S_PALLET = first(SF, ["pallet"])


# Find products.xls
relation_field = None

for f in SourceRow._meta.get_fields():

    if not getattr(f, "many_to_one", False):
        continue

    related = getattr(f, "related_model", None)

    if related and "original_filename" in fields(related):
        relation_field = f.name
        break


source_qs = SourceRow.objects.all()


if relation_field:

    ExternalFile = SourceRow._meta.get_field(
        relation_field
    ).related_model

    ext = (
        ExternalFile.objects
        .filter(original_filename__iexact=TARGET_FILENAME)
        .order_by("-pk")
        .first()
    )

    if ext:
        source_qs = source_qs.filter(
            **{relation_field: ext}
        )


products = {}

for p in Product.objects.all():

    sku = txt(getattr(p, P_SKU, ""))

    if sku:
        products[sku] = p


sources = {}

for s in source_qs:

    sku = txt(getattr(s, S_SKU, ""))

    if sku:
        sources[sku] = s


matched = sorted(
    set(products) & set(sources)
)


counts = Counter()
signatures = Counter()
examples = defaultdict(list)


for sku in matched:

    p = products[sku]
    s = sources[sku]

    diff = []


    # ------------------------
    # Name / Description
    # ------------------------

    if txt(getattr(p, P_NAME, "")) != txt(
        getattr(s, S_NAME, "")
    ):
        diff.append("NAME")
        counts["NAME"] += 1


    if txt(getattr(p, P_DESC, "")) != txt(
        getattr(s, S_DESC, "")
    ):
        diff.append("DESCRIPTION")
        counts["DESCRIPTION"] += 1


    # ------------------------
    # Dimensions
    # ------------------------

    calc_length = dec(
        getattr(p, P_LENGTH, None)
    )

    calc_width = dec(
        getattr(p, P_WIDTH, None)
    )

    calc_height = dec(
        getattr(p, P_HEIGHT, None)
    )


    src_length = source_dimension_to_metres(
        getattr(s, S_LENGTH, None),
        S_LENGTH
    )

    src_width = source_dimension_to_metres(
        getattr(s, S_WIDTH, None),
        S_WIDTH
    )

    src_height = source_dimension_to_metres(
        getattr(s, S_HEIGHT, None),
        S_HEIGHT
    )


    if not same(calc_length, src_length):
        diff.append("LENGTH")
        counts["LENGTH"] += 1


    if not same(calc_width, src_width):
        diff.append("WIDTH")
        counts["WIDTH"] += 1


    if not same(calc_height, src_height):
        diff.append("HEIGHT")
        counts["HEIGHT"] += 1


    # ------------------------
    # Weight
    # ------------------------

    calc_weight = dec(
        getattr(p, P_WEIGHT, None)
    )

    src_weight = dec(
        getattr(s, S_WEIGHT, None)
    )


    if not same(calc_weight, src_weight):

        diff.append("WEIGHT")
        counts["WEIGHT"] += 1


    # ------------------------
    # Cubic
    # ------------------------

    calc_cubic = dec(
        getattr(p, P_CUBIC, None)
    )

    src_cubic = dec(
        getattr(s, S_CUBIC, None)
    )


    if not same(calc_cubic, src_cubic):

        diff.append("CUBIC")
        counts["CUBIC"] += 1


    # ------------------------
    # Case / Pallet
    # ------------------------

    calc_cp = txt(
        getattr(p, P_CP, "")
    ).upper()


    pallet = dec(
        getattr(s, S_PALLET, None)
    )


    if pallet is None or pallet < 0:

        source_cp = "NEEDS_REVIEW"
        counts["PALLET_INVALID"] += 1

    elif pallet == 0:

        source_cp = "C"

    else:

        source_cp = "P"


    if (
        source_cp in ("C", "P")
        and calc_cp
        and source_cp != calc_cp
    ):

        diff.append("CASE_PALLET")
        counts["CASE_PALLET"] += 1


    signature = tuple(diff)

    signatures[signature] += 1


    if len(examples[signature]) < 8:

        examples[signature].append(
            (
                sku,
                calc_length,
                src_length,
                calc_width,
                src_width,
                calc_height,
                src_height,
                calc_weight,
                src_weight,
                calc_cubic,
                src_cubic,
                calc_cp,
                source_cp,
            )
        )


print("=" * 90)

print(
    "CORRECTED PHYSICAL COMPARISON"
)

print("=" * 90)

print(
    "Matched products:",
    len(matched)
)

print()


for key in [
    "NAME",
    "DESCRIPTION",
    "LENGTH",
    "WIDTH",
    "HEIGHT",
    "WEIGHT",
    "CUBIC",
    "CASE_PALLET",
    "PALLET_INVALID",
]:

    print(
        f"{key:<20}",
        counts[key]
    )


print()

print("=" * 90)

print(
    "CORRECTED DIFFERENCE SIGNATURES"
)

print("=" * 90)


ordered = sorted(
    signatures.items(),
    key=lambda item: -item[1]
)


for signature, count in ordered:

    label = (
        " + ".join(signature)
        if signature
        else "SAME"
    )

    print()

    print(
        f"{count:>4}  {label}"
    )

    print(
        "      examples:",
        ", ".join(
            row[0]
            for row
            in examples[signature]
        )
    )


print()

print("=" * 90)

print(
    "GROUPS WITH 122 PRODUCTS"
)

print("=" * 90)


found = False


for signature, count in ordered:

    if count == 122:

        found = True

        print(
            "122:",
            " + ".join(signature)
        )


if not found:

    print(
        "No corrected difference signature has exactly 122 products."
    )


print()

print("=" * 90)

print(
    "CASE/PALLET DIFFERENCE DETAILS"
)

print("=" * 90)


for signature, rows in examples.items():

    if "CASE_PALLET" not in signature:
        continue

    for row in rows:

        (
            sku,
            cl,
            sl,
            cw,
            sw,
            ch,
            sh,
            cweight,
            sweight,
            ccubic,
            scubic,
            ccp,
            scp,
        ) = row

        print()

        print("SKU:", sku)

        print(
            "Calculator C/P:",
            ccp
        )

        print(
            "Source-derived C/P:",
            scp
        )

        print(
            "Calculator dimensions:",
            cl,
            cw,
            ch
        )

        print(
            "Source dimensions:",
            sl,
            sw,
            sh
        )

        print(
            "Weight:",
            cweight,
            "vs",
            sweight
        )

        print(
            "Cubic:",
            ccubic,
            "vs",
            scubic
        )


print()

print(
    "READ ONLY - NO DATABASE CHANGES MADE"
)