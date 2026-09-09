$ErrorActionPreference = "Stop"

Write-Host "Applying Cubic Margin option 1 patch..."

$files = @(
  "app\apps\freight\services\dtos.py",
  "app\apps\freight\views.py",
  "app\apps\freight\services\calculator.py",
  "app\templates\freight\calculator.html",
  "app\static\css\app.css"
)

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
foreach ($file in $files) {
  if (!(Test-Path $file)) {
    throw "File not found: $file"
  }
  Copy-Item $file "$file.bak_cubic_margin_$stamp" -Force
}

@'
from pathlib import Path

# 1) FreightRequest DTO: add optional cubic_margin_percent, default 0.
dtos_path = Path(r"app/apps/freight/services/dtos.py")
dtos = dtos_path.read_text(encoding="utf-8")
if "cubic_margin_percent" not in dtos:
    old = "    lines: list[FreightLine] = field(default_factory=list)\n"
    new = "    lines: list[FreightLine] = field(default_factory=list)\n    cubic_margin_percent: Decimal = Decimal('0')\n"
    if old not in dtos:
        raise SystemExit("dtos.py: expected FreightRequest lines field not found.")
    dtos = dtos.replace(old, new)
    dtos_path.write_text(dtos, encoding="utf-8")

# 2) views.py: pass cubic_margin_percent from JSON payload to FreightRequest.
views_path = Path(r"app/apps/freight/views.py")
views = views_path.read_text(encoding="utf-8")
if "cubic_margin_percent=_decimal(payload.get('cubic_margin_percent'), '0')" not in views:
    old = "            preselect_sku=str(payload.get('preselect_sku', 'YES')).upper() == 'YES',\n            lines=lines,\n        )"
    new = "            preselect_sku=str(payload.get('preselect_sku', 'YES')).upper() == 'YES',\n            lines=lines,\n            cubic_margin_percent=_decimal(payload.get('cubic_margin_percent'), '0'),\n        )"
    if old not in views:
        raise SystemExit("views.py: expected FreightRequest construction block not found.")
    views = views.replace(old, new)
    views_path.write_text(views, encoding="utf-8")

# 3) calculator.py: apply margin to rating cubic only when requested.
calc_path = Path(r"app/apps/freight/services/calculator.py")
calc = calc_path.read_text(encoding="utf-8")

if "from dataclasses import replace" not in calc:
    calc = calc.replace("from decimal import Decimal, ROUND_UP, ROUND_HALF_UP\n", "from dataclasses import replace\nfrom decimal import Decimal, ROUND_UP, ROUND_HALF_UP\n")

if "from .validators import validate_location, validate_consolidated, ValidationError" not in calc:
    calc = calc.replace(
        "from .validators import validate_location, validate_consolidated\n",
        "from .validators import validate_location, validate_consolidated, ValidationError\n",
    )

if "MAX_CUBIC_MARGIN_PERCENT" not in calc:
    insert = '''\n\nMAX_CUBIC_MARGIN_PERCENT = Decimal('15')\n\n\ndef apply_cubic_margin(consolidated, margin_percent: Decimal):\n    """Apply optional cubic margin to visible/product cubic before carrier rating.\n\n    The default margin is 0%, so the Excel validation batteries remain unchanged.\n    The margin is applied only to product-visible cubic. Pallet cubic is added\n    back afterwards because Excel treats pallet cubic as a separate internal\n    rating allowance.\n    """\n    margin_percent = Decimal(str(margin_percent or '0'))\n\n    if margin_percent < Decimal('0'):\n        raise ValidationError('Cubic margin percent cannot be negative')\n    if margin_percent > MAX_CUBIC_MARGIN_PERCENT:\n        raise ValidationError('Cubic margin percent cannot be greater than 15')\n    if margin_percent == Decimal('0'):\n        return consolidated\n\n    pallet_cubic = (\n        consolidated.pallet_count * PALLET_CUBIC_M3\n        if consolidated.pallet_count > Decimal('0.99')\n        else Decimal('0')\n    )\n    visible_cubic = consolidated.cubic_total_m3 - pallet_cubic\n    adjusted_visible_cubic = (\n        visible_cubic * (Decimal('1') + (margin_percent / Decimal('100')))\n    ).quantize(Decimal('0.001'), rounding=ROUND_UP)\n    adjusted_rating_cubic = (\n        adjusted_visible_cubic + pallet_cubic\n    ).quantize(Decimal('0.001'), rounding=ROUND_UP)\n\n    return replace(consolidated, cubic_total_m3=adjusted_rating_cubic)\n'''
    marker = "\n\ndef _teamex_weight_break(weight: Decimal) -> str:\n"
    if marker not in calc:
        raise SystemExit("calculator.py: insertion point before _teamex_weight_break not found.")
    calc = calc.replace(marker, insert + marker)

old = "        consolidated = consolidate_lines(request.lines, request.tailgate)\n        validate_consolidated(consolidated)\n"
new = "        consolidated = consolidate_lines(request.lines, request.tailgate)\n        consolidated = apply_cubic_margin(consolidated, request.cubic_margin_percent)\n        validate_consolidated(consolidated)\n"
if old in calc and "apply_cubic_margin(consolidated, request.cubic_margin_percent)" not in calc:
    calc = calc.replace(old, new)
elif "apply_cubic_margin(consolidated, request.cubic_margin_percent)" not in calc:
    raise SystemExit("calculator.py: consolidate/validate block not found.")

calc_path.write_text(calc, encoding="utf-8")

# 4) calculator.html: add Cubic Margin selector and send it in the calculate payload.
template_path = Path(r"app/templates/freight/calculator.html")
html = template_path.read_text(encoding="utf-8")

if 'id="cubic_margin_percent"' not in html:
    old = '''      <label>Use Preselected SKU Mode\n        <select id="preselect_sku"><option>YES</option><option>NO</option></select>\n      </label>'''
    new = '''      <label>Use Preselected SKU Mode\n        <select id="preselect_sku"><option>YES</option><option>NO</option></select>\n      </label>\n      <label>Cubic Margin\n        <select id="cubic_margin_percent">\n          <option value="0">0% - No margin</option>\n          <option value="10">10% - Standard packing margin</option>\n          <option value="15">15% - Conservative packing margin</option>\n        </select>\n      </label>'''
    if old not in html:
        raise SystemExit("calculator.html: preselect_sku label block not found.")
    html = html.replace(old, new)

if "cubic_margin_percent:document.getElementById('cubic_margin_percent').value" not in html:
    old = "preselect_sku:document.getElementById('preselect_sku').value,lines"
    new = "preselect_sku:document.getElementById('preselect_sku').value,cubic_margin_percent:document.getElementById('cubic_margin_percent').value,lines"
    if old not in html:
        raise SystemExit("calculator.html: payload preselect_sku/lines block not found.")
    html = html.replace(old, new)

template_path.write_text(html, encoding="utf-8")

# 5) app.css: make top calculator grid fit the additional selector on desktop.
css_path = Path(r"app/static/css/app.css")
css = css_path.read_text(encoding="utf-8")
old = ".calculator-grid{display:grid;grid-template-columns:minmax(210px,1.25fr) minmax(230px,1.35fr) minmax(86px,.46fr) minmax(98px,.52fr) minmax(115px,.58fr) minmax(170px,.85fr);column-gap:14px;row-gap:10px;align-items:end}"
new = ".calculator-grid{display:grid;grid-template-columns:minmax(185px,1.15fr) minmax(215px,1.3fr) minmax(72px,.42fr) minmax(90px,.48fr) minmax(100px,.54fr) minmax(150px,.78fr) minmax(145px,.74fr);column-gap:14px;row-gap:10px;align-items:end}"
if old in css:
    css = css.replace(old, new)
# If the exact CSS has already been changed, do nothing rather than rewriting unrelated styles.
css_path.write_text(css, encoding="utf-8")

print("OK: Cubic Margin option 1 applied.")
'@ | python

Write-Host "Validating Python syntax..."
python -m py_compile .\app\apps\freight\services\dtos.py
python -m py_compile .\app\apps\freight\views.py
python -m py_compile .\app\apps\freight\services\calculator.py

Write-Host "Done. Backups created with suffix: .bak_cubic_margin_$stamp"
