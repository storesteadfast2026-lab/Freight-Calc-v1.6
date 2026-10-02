# Continue Calculator App development

Attach `Calculator_App_Continuity_LATEST.zip` to a new chat or Work session and say:

> Continue Calculator App development using this Continuity Snapshot as the authoritative current state.

Read `CURRENT_STATE.md` first. Verify `FILE_HASHES.csv`, inspect `BASELINE_CODE.zip`, and use `DB_STATE.json` and `PRODUCT_STATE.txt` for the database snapshot. The next change must still be validated against the **physical installed project and current database** before writing or creating an incremental package. A snapshot is a point-in-time development reference, not a replacement for a database backup or an authorisation to change operational data.

`BASELINE_CODE.zip` contains an allowlisted source tree, not uploaded data, settings containing local credentials, Git history, virtual environments or the complete database. Any unavailable comparison is labelled; do not infer counts from missing data. Use `tools/Create_Continuity_Snapshot.bat` to refresh this archive after authorised changes.

When preparing a later incremental package, make its `04_Verify_Update.bat` run the installed snapshot tool **only after** its own main verification succeeds. Report snapshot failure separately. Earlier packages already distributed cannot gain this hook retroactively.
