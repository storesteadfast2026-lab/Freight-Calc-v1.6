# Product/Stock Admin hotfix 0720.1446

## Symptom

The `External data files` page showed the new `Products` and `Stock` file-type filters, but it did not show:

- `Upload product source`
- `Upload stock source`
- `Product source rows`
- `Stock source rows`

## Diagnosis

The model and migration changes were active, but Django Admin was still loading the previous `admin.py` and/or previous `change_list.html` template.

## Correction

This hotfix forces replacement of:

- `app/apps/imports/admin.py`
- `app/templates/admin/imports/externaldatafile/change_list.html`
- `app/templates/admin/imports/externaldatafile/upload_source.html`
- `app/templates/admin/imports/externaldatafile/reference_validation_summary.html`

The application script validates:

- the two custom Admin URLs;
- the template origin loaded by Django;
- the presence of the two upload labels in the active template;
- registration of `ProductSourceRow` and `StockSourceRow` in Django Admin.

No operational calculation, Product, FreightRate, FreightZone, carrier configuration or fuel logic is changed.
