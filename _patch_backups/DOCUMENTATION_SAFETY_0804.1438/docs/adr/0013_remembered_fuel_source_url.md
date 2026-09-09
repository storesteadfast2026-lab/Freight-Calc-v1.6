# ADR 0013 — Remembered Fuel source URL

## Status

Accepted and implemented in source on 2026-08-03.

## Context

`Fetch fuel from source` displayed `FUEL_SOURCE_URL` as fixed text and always
downloaded from that setting. Administrators need to change the source when its
location moves and have the last valid location available on the next fetch.

`ExternalDataFile` already records `client`, `file_type`, `source_method`,
`source_url`, validation status, SHA-256 and timestamps. Adding another source
configuration table would duplicate this history for the current requirement.

Product and Stock currently use browser-local file uploads rather than remote
URLs. Browsers do not expose or permit a server to prefill the user's local
directory.

## Decision

- Add an editable HTTP/HTTPS `Fuel source URL` field to the Fetch form.
- Pass the selected URL explicitly to the Fuel download service.
- Store it in the existing immutable `ExternalDataFile` and audit metadata.
- For each client, prefill the latest URL from a successfully validated
  `ADMIN_WEB_FETCH` Fuel record.
- Fall back to `FUEL_SOURCE_URL` when that client has no qualifying history.
- Do not remember failed downloads or failed validations.
- Keep activation as a separate explicit operation.
- Leave Product and Stock local upload behavior unchanged.

## Consequences

- No database migration is required.
- Each client retains an independent remembered Fuel source.
- Changing the acquisition URL cannot directly change operational Fuel rates.
- Future remote Product/Stock sources require a separate approved extension;
  they are not implied by this decision.
