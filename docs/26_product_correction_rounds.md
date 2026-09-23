# Product correction rounds (same Source)

Once products.xls has an active initial Apply, use Review protected differences / correction rounds. Start one draft round, open a SKU, choose field authorities and enter a reason. Save several SKUs, open Preview, then explicitly Apply the round. A later round can use the same ExternalDataFile without reuploading it. Original ProductReconciliationDecision rows remain APPLIED, with new ProductCorrectionDecision rows retained per round. Memory is updated at Apply, and rollback restores the previous memory.

Source zero dimensions cannot be selected. Scale warnings require explicit unit confirmation; custom dimensions remain available. A Source fingerprint and complete Product snapshot are checked immediately before Apply. All selected changes apply in one transaction. Roll back correction rounds newest first before any rollback of the initial Apply.

A current physical difference count does not necessarily decrease by one for every applied correction: some Source/Calculator differences can remain intentionally after review. The screen tracks reviewed SKUs separately, with Show all available for another correction. No Product changes occur on Start or Save.

Deployment: run `docker compose exec -T web python manage.py migrate`, then `docker compose exec -T web python manage.py check` and `docker compose exec -T web python manage.py test apps.imports.tests.test_product_reconciliation_workspace`. The installer's rollback is for code files only: it does not undo database migrations or applied correction rounds.
