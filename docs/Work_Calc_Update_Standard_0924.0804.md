# Work.Calc update standard — 24 September 2026, 08:04 Adelaide time

This is the continuing operating agreement for Work.Calc at
`C:\Docker-Projects\Freight-Calc-v1.6`. Carry it into future chats and review it
before preparing or applying another Work.Calc update. It records the procedure
consolidated in `work.calc.old` and the corrections made after the CUSTOMER
installer rejected an unrecognised installed file.

## Scope and current state

- Work.Calc is a Django 5.1 / PostgreSQL 16 application run through Docker
  Compose. STH is one calculator tenant. CUSTOMER in `products.xls` identifies
  a commercial customer **within** that tenant. Tenant access and CUSTOMER
  product identity must not be conflated.
- Historical Product source #11 has an initial Apply and approximately 107
  protected differences. Correction rounds must continue to use the original
  immutable source and preserve the decisions and their audit history.
- The current CUSTOMER update is based on the actual Windows project export
  `Current_Project_For_CUSTOMER_20260924_075130.zip`. Its
  `app/apps/imports/models.py` SHA-256 is
  `da728a67064d2653950036292c2e62ac1be3edde7d054c2057b389905c045b7e`.
  Re-export if the Windows project changes after this baseline.

## Package contract

| File | Purpose |
| --- | --- |
| `01_Open_PowerShell_Here.bat` | Open PowerShell at the extracted package. Never install or automatically launch step 02. |
| `02_Apply_Update.bat` | Run `Apply_Update.ps1` with preflight, backup, incremental file changes and validation. |
| `03_Rollback_Update.bat` | Run `Rollback_Update.ps1` separately using the recorded backup; protect subsequent edits and database data. |
| `04_Export_Project.bat` | Export only relevant current code and migrations when the baseline check fails. Never alter the project, database or containers. |
| `payload/`, `MANIFEST.csv`, `README_MMDD.HHmm.md` | Changed files only, exact old and new SHA-256 hashes, installation and recovery instructions. |

Name every delivered ZIP `Calc_<Change>_MMDD.HHmm.zip` using Adelaide local
time. Use the **01–04** sequence for Work.Calc. The `00` launcher used by
some PON packages is a separate convention and does not apply here.

## Before delivery

1. Compare the proposed code with the **latest installed-project export**,
   not solely an older snapshot or a previous package. Compare both the
   semantic diff and exact bytes. Windows line endings can change SHA-256
   without changing Python or template behaviour. Preserve intervening UI
   fixes, such as removal of the duplicated reconciliation title.
2. Verify the ZIP contains 01, 02, 03, 04, the matching PowerShell scripts,
   README, manifest and every payload file. Check the ZIP CRC, each incoming
   SHA-256 and all expected old hashes against the actual export.
3. Run relevant automated tests, Django checks and migration checks in a
   disposable environment. Do not claim that an installer was tested on the
   recipient's Windows host unless it actually was.
4. Save a versioned ZIP and this procedure. Do not make remote Git changes
   automatically.

## Installation and recovery

1. Extract the ZIP into Downloads, open **01**, then run
   `.\02_Apply_Update.bat` in the PowerShell window.
2. Step 02 checks the project root and exact installed hashes before any
   project file changes. If a file is unsupported, stop with **zero project
   file changes**. Run **04**, upload its `Current_Project_*.zip`, review the
   difference and build a new versioned update. Do not bypass the hash check
   or keep retrying step 02.
3. Before copying payload, save the files that will be replaced and a
   PostgreSQL dump if schema or data may be affected. Keep backups and logs
   persistently under `update_backups/<PackageName>`; never automatically
   prune them, which retains at least the most recent five successful
   backups. Record installed hashes and created files in `INSTALL_STATE.csv`.
4. Stop web only after preflight and backup. Copy changed files, run focused
   tests, apply required migrations, restart web and check Django. Rebuild
   the image only when dependencies or the image contents change; the
   current source code is bind-mounted into the container.
5. If step 02 fails after migration begins, reverse the migrations introduced
   by that package **while its new code is present**, restore backed-up files,
   and restart web. If schema reversal fails, keep web stopped and retain
   the PostgreSQL dump and files for manual recovery. Never describe a code
   restore as a complete rollback while the schema still differs.
6. Use **03** only for a completed installation. Verify installed and backed-up
   file hashes, block rollback once new CUSTOMER data has been used, reverse
   the package's migrations before restoring old code, then restart and
   validate web. Retain backup and logs. When data has already been used,
   stop and plan a forward correction or a separately reviewed database
   recovery; do not silently discard data.

## Review of the CUSTOMER packages

`Calc_Product_CUSTOMER_0924.0757.zip` contains the incremental payload,
scripts 01–04, exact installed baseline checks, a PostgreSQL backup and
`INSTALL_STATE.csv`. It also preserves the existing reconciliation title fix.
It needs replacement before use because its apply recovery and manual step 03
restore code while leaving the CUSTOMER database migration in place. That can
leave the old application running against a changed uniqueness constraint.

`Calc_Product_CUSTOMER_0924.0804.zip` addresses that gap: step 02 runs the
focused CUSTOMER tests before migrating, reverses this package's migrations
on post-migration failure, and step 03 reverses them during a safe manual
rollback. Both steps write execution logs. Continue to require a fresh
export if any exact installed hash changes. This package was verified against
the 07:51 Windows export; running it on the Windows installation remains the
user's next step.

## Domain changes carried by the CUSTOMER update

- Product identity becomes `(calculator tenant, CUSTOMER, SKU)`; old Products
  have a blank CUSTOMER until reviewed. New `products.xls` sources use the
  CUSTOMER header while historical sources remain immutable.
- Reconciliation, correction rounds, selection, quotes and Stock comparisons
  use the appropriate identity. Historical correction rounds keep their
  operational Product IDs and decision audit trail.
- The `review_product_customers` management command proposes mappings only
  for unambiguous SKUs, requires explicit approval and records an audit.
  The new source cannot Apply while old Products still lack CUSTOMER.
- Installation changes no live Product customer assignment by itself.

For this update the area test suite passed **202 tests** on SQLite, Django
`check` reported no issues, and `makemigrations --check --dry-run` reported no
missing migrations. These checks do not substitute for observing the first
Windows installation and its logs.
