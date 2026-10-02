# Calculator App rules preserved for continuation

- `Customer` is the imported Translogic customer. A linked `Client` is its Calculator Customer. The special `* / All Customers` cannot own Product Master or become a Calculator Customer.
- `products.xls` is a global Product Master. Its `CUSTOMER` column resolves the `Customer` by code and then its linked Calculator Customer; Product identity is `Client + SKU`. Do not add `Product.customer_code`.
- `ExternalDataFile` remains scoped to one Calculator Customer. Product Master uploads and comparison are separate from that upload flow.
- Customer access and authorisation are enforced in the backend. Global Product Master data must be exposed only within the authorised Calculator Customer scope.
- Product Master comparison, Product Reconciliation, Correction Rounds, decisions and Reconciliation Memory are the existing workflow. Review and Preview must not modify operational Products. Explicit Apply is required; preserve audit/history and guarded business rollback.
- Source-only import creates only missing Products for the selected Calculator Customer, using existing validation, unit conversion and freight type rules. Ineligible rows stay pending.
- Incremental updates use `01_Open_PowerShell_Here.bat`, `02_Apply_Update.bat`, `03_Rollback_Update.bat` and `04_Verify_Update.bat`, with baseline checks, backups, hashes, logs and rollback. Do not modify Git remote automatically.
- Future incremental packages should call the installed `tools/Create_Continuity_Snapshot.ps1` after their own `04_Verify_Update.bat` verification succeeds. Historical ZIP files cannot be changed retroactively.

These are curated project decisions. The generated state and code archive, taken from the actual installation, determine what is currently implemented.

## Known points to revalidate

- In the development export on 29 September 2026, the full suite had four login-message expectation failures and two saved-estimate email-template failures. These are **not** a claim about the installed project's current test result; rerun the full suite to confirm or close them.
