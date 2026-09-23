# Freight Calculator v1.6 — Memory Excel and Bulk Reuse 0923.0848

## Added

- One-click **Reuse all previous approved solutions** for exact Source matches.
- Review counters and filters for exact memory, changed Source, new issues and
  active reusable-rule matches.
- **Download memory Excel** from Product reconciliation.
- Filter-aware Excel export from External Data Correction Memory Admin.
- Flattened Source, approved solution, provenance, audit and reuse fields for
  human or AI-assisted review.
- Automatic ZIP splitting every 25,000 memory records.

## Safety

- Bulk reuse creates or refreshes drafts only; it never updates Products.
- Changed Source values remain manual-review items.
- Already applied decisions are not overwritten by bulk reuse.
- Export is read-only and audited.
- `.xlsx` is used instead of legacy `.xls` to avoid its 65,536-row limit.
