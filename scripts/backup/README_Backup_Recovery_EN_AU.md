# Freight Calculator - Backup and Recovery

This package separates three concerns:

1. Application code: Git and a local Git bundle.
2. PostgreSQL structure: `database/schema.sql`, suitable for versioning with the code.
3. Operational data: PostgreSQL custom-format dumps stored outside the repository.

## Scripts

### 01_Full_Backup.ps1
Creates a timestamped local recovery point containing:
- PostgreSQL custom-format database dump.
- PostgreSQL globals/roles.
- PostgreSQL schema-only snapshot.
- Basic database inventory.
- Local Git bundle containing local branches and tags.
- SHA256 checksums.
- Recovery manifest.
- Optional secondary copy.

It does not change the production database.

### 02_Test_PostgreSQL_Restore.ps1
Restores a selected dump into an isolated temporary database, validates it,
creates and validates a secondary dump, then removes the temporary database
unless `-KeepTestDatabase` is specified.

It does not change `freight_platform`.

### 03_Restore_PostgreSQL_Production.ps1
Emergency production restore procedure. It:
- requires an exact typed confirmation;
- validates the selected dump;
- creates an emergency backup of current production;
- restores first into an isolated database;
- validates the isolated restore;
- stops the Django web service;
- retains the previous production database by renaming it;
- promotes the restored database;
- restarts Django and runs a database-aware system check;
- attempts an automatic database-name rollback if the post-swap check fails.

Use only for a real recovery.

### 04_Update_Database_Schema.ps1
Generates `database/schema.sql` using `pg_dump --schema-only`, rebuilds a
temporary database from that SQL to prove that the structure is usable, and
shows local Git status/diff information.

No operational data is exported.

### 05_Install_Daily_Backup_Task.ps1
Registers a Windows Scheduled Task for `01_Full_Backup.ps1`.

The default schedule is 19:00 each day.

The task uses the signed-in Windows account with LIMITED privileges so it can
work with Docker Desktop in the user's interactive session without requiring
unnecessary elevation.

## Recommended workflow

- Daily: run `01_Full_Backup.ps1` automatically.
- Before important data changes: run `01_Full_Backup.ps1` manually.
- When versioning code/database structure: run `04_Update_Database_Schema.ps1`
  and review `database/schema.sql`.
- Periodically: validate a recent dump using `02_Test_PostgreSQL_Restore.ps1`.
- For a real database recovery only: use `03_Restore_PostgreSQL_Production.ps1`.

## Backup storage

Operational dumps should remain outside the project repository, for example:

`C:\Docker-Backups\Freight-Calc\`

For stronger resilience, keep a second copy on independent storage and an
off-site copy where practical.
