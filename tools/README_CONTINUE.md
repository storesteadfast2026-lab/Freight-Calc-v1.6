# Continue Calculator App development

Attach `Calculator_App_Continuity_LATEST.zip` to a new chat or Work session and say:

> Continue Calculator App development using this Continuity Snapshot as the authoritative current state.

Read `CURRENT_STATE.md` first. Verify `FILE_HASHES.csv`, inspect `BASELINE_CODE.zip`, and use `DB_STATE.json` and `PRODUCT_STATE.txt` for the database snapshot. The next change must still be validated against the **physical installed project and current database** before writing or creating an incremental package. A snapshot is a point-in-time development reference, not a replacement for a database backup or an authorisation to change operational data.

`BASELINE_CODE.zip` contains an allowlisted source tree, not uploaded data, settings containing local credentials, Git history, virtual environments or the complete database. Any unavailable comparison is labelled; do not infer counts from missing data. Run `05_Create_Continuity_Snapshot.bat` manually to refresh this archive after authorised changes.

When preparing a later incremental package, preserve `04 = Verify only` and `05 = Manual Continuity Snapshot only`. Never invoke snapshot creation from Apply, rollback or Verify. Historical ZIP files cannot be changed retroactively; use the latest package's verification launcher.
