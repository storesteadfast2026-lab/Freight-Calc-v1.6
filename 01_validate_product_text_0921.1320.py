from django.apps import apps
from decimal import Decimal, InvalidOperation
import re


def find_model(name):
    for model in apps.get_models():
        if model.__name__ == name:
            return model
    raise RuntimeError(f"Model not found: {name}")


Product = find_model("Product")
SourceRow = find_model("ProductSourceRow")


def fields(model):
    return {
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "concrete", False)
    }


PF = fields(Product)
SF = fields(SourceRow)


def first(existing, candidates):
    for name in candidates:
        if name in existing:
            return name
    return None


# Operational Product
P_SKU = first(PF, ["sku", "code", "product_code"])
P_NAME = first(PF, ["name", "product_name"])
P_DESC = first(PF, ["description", "desc"])
P_LEN = first(PF, ["length_m", "length", "length_mm"])
P_WID = first(PF, ["width_m", "width", "width_mm"])

# Source Product
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
S_NAME = first(SF, ["name", "product_name"])
S_DESC = first(SF, ["description", "desc"])

print("FIELD MAPPING")
print("-------------")
print("Product SKU:", P_SKU)
print("Product Name:", P_NAME)
print("Product Description:", P_DESC)
print("Product Length:", P_LEN)
print("Product Width:", P_WID)
print("Source SKU:", S_SKU)
print("Source Name:", S_NAME)
print("Source Description:", S_DESC)
print()


# Find the newest products.xls ExternalDataFile automatically
relation_field = None

for f in SourceRow._meta.get_fields():
    if getattr(f, "many_to_one", False):
        related = getattr(f, "related_model", None)
        if related:
            related_fields = fields(related)
            if "original_filename" in related_fields:
                relation_field = f.name
                break


source_qs = SourceRow.objects.all()
selected_file = None

if relation_field:
    related_model = SourceRow._meta.get_field(
        relation_field
    ).related_model

    matches = related_model.objects.filter(
        original_filename__iexact="products.xls"
    ).order_by("-pk")

    selected_file = matches.first()

    if selected_file:
        source_qs = source_qs.filter(
            **{relation_field: selected_file}
        )


print("SOURCE FILE")
print("-----------")

if selected_file:
    print("ID:", selected_file.pk)
    print(
        "Filename:",
        getattr(selected_file, "original_filename", "")
    )
else:
    print("WARNING: products.xls could not be isolated.")

print("Source rows:", source_qs.count())
print()


def text(value):
    if value is None:
        return ""
    return str(value).strip()


def number(value):
    value = text(value)

    if not value:
        return None

    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value):
        return None

    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def dimension_in_metres(obj, field):
    if not field:
        return None

    value = getattr(obj, field, None)

    try:
        value = Decimal(str(value))
    except:
        return None

    if field.endswith("_mm"):
        return value / Decimal("1000")

    return value


source = {}

for row in source_qs.iterator():

    sku = text(getattr(row, S_SKU, ""))

    if sku:
        source[sku] = row


products = {}

for product in Product.objects.all():

    sku = text(getattr(product, P_SKU, ""))

    if sku:
        products[sku] = product


matched = set(products) & set(source)

operational_only = set(products) - set(source)
source_only = set(source) - set(products)


name_diff = 0
description_diff = 0
either_text_diff = 0
both_text_diff = 0

name_numeric = 0
description_numeric = 0
both_numeric = 0

name_equals_old_length = 0
description_equals_old_width = 0
historical_mapping = 0


examples = []


for sku in sorted(matched):

    p = products[sku]
    s = source[sku]

    calc_name = text(getattr(p, P_NAME, ""))
    calc_desc = text(getattr(p, P_DESC, ""))

    src_name = text(getattr(s, S_NAME, ""))
    src_desc = text(getattr(s, S_DESC, ""))

    nd = calc_name != src_name
    dd = calc_desc != src_desc

    name_diff += nd
    description_diff += dd
    either_text_diff += nd or dd
    both_text_diff += nd and dd

    n_num = number(calc_name)
    d_num = number(calc_desc)

    if n_num is not None:
        name_numeric += 1

    if d_num is not None:
        description_numeric += 1

    if n_num is not None and d_num is not None:
        both_numeric += 1

    length_m = dimension_in_metres(p, P_LEN)
    width_m = dimension_in_metres(p, P_WID)

    name_old_length = False
    desc_old_width = False

    if n_num is not None and length_m is not None:
        name_old_length = (
            abs(
                n_num -
                (length_m * Decimal("100"))
            )
            <= Decimal("0.01")
        )

    if d_num is not None and width_m is not None:
        desc_old_width = (
            abs(
                d_num -
                (width_m * Decimal("100"))
            )
            <= Decimal("0.01")
        )

    name_equals_old_length += name_old_length
    description_equals_old_width += desc_old_width

    if name_old_length and desc_old_width:

        historical_mapping += 1

        if len(examples) < 20:
            examples.append(
                (
                    sku,
                    calc_name,
                    calc_desc,
                    length_m,
                    width_m,
                    src_name,
                    src_desc,
                )
            )


print("=" * 70)
print("RESULTS")
print("=" * 70)

print("Operational Products:                 ", len(products))
print("Source unique SKUs:                   ", len(source))
print("Matched Calculator <-> Source:        ", len(matched))
print("Operational only:                     ", len(operational_only))
print("Source only / new:                    ", len(source_only))

print()

print("Name different:                       ", name_diff)
print("Description different:                ", description_diff)
print("Name OR Description different:        ", either_text_diff)
print("Name AND Description different:       ", both_text_diff)

print()

print("Calculator Name numeric:              ", name_numeric)
print("Calculator Description numeric:       ", description_numeric)
print("Both Name + Description numeric:      ", both_numeric)

print()

print("Name = old Length(cm):                ", name_equals_old_length)
print("Description = old Width(cm):          ", description_equals_old_width)

print(
    "Historical mapping pattern BOTH:      ",
    historical_mapping
)

print()

print("EXAMPLES")
print("--------")

for (
    sku,
    calc_name,
    calc_desc,
    length_m,
    width_m,
    src_name,
    src_desc,
) in examples:

    print()
    print("SKU:", sku)
    print(
        "Calculator:",
        calc_name,
        "/",
        calc_desc
    )
    print(
        "Dimensions:",
        length_m,
        "x",
        width_m,
        "m"
    )
    print(
        "Source:",
        src_name,
        "/",
        src_desc
    )


print()
print("READ ONLY - NO DATABASE CHANGES MADE")