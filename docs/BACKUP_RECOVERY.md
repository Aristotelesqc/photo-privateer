# Back up and recover a local catalog

Run these commands from the repository root with its Python environment activated. Maintenance is local and offline: it does not start the server, open a browser, load Google credentials or call a search provider. Always specify the profile explicitly. The normal profile is `$HOME\.photo_privateer`; `PHOTO_PRIVATEER_DATA_DIR` can select another one.

Atomic publication of a new bundle or profile is supported on Windows and Linux. Other platforms, including macOS, fail safely if the required atomic no-replace operation is unavailable.

## Create and verify a backup

Choose an output directory that does not exist:

```powershell
python -m backend.maintenance backup --profile "$HOME\.photo_privateer" --output "D:\PhotoPrivateerBackups\2026-10-04"
python -m backend.maintenance verify "D:\PhotoPrivateerBackups\2026-10-04"
```

Each successful command prints a small JSON summary and exits with code 0. Invalid arguments exit with code 2; maintenance failures print the reason to stderr and exit with code 1. Keep the entire bundle directory together, including `manifest.json` and its payloads.

The database is copied through SQLite's backup API, including committed data in WAL. A writer reservation holds the catalog stable while registered artifacts are copied. The app can remain open for an explicit backup, but prefer an idle catalog or stop the app first: writes are blocked for the duration, and a long copy can exceed the app's 10-second SQLite busy timeout. Maintenance never initiates a scan.

The bundle contains:

- A standalone catalog snapshot: photo metadata, libraries, groups and lineage, review decisions and their observation/rollback history, rules, usage, sessions and non-secret settings.
- Immutable local files registered in `catalog_artifacts`, with their exact relative paths, SHA-256 hashes, sizes and kinds (`evidence` or `case_attachment`). This registry supports future evidence and case features; those user-facing features are not implemented by this recovery workflow. Every future feature must register its owned blobs transactionally rather than rely on copying arbitrary profile files.
- A versioned manifest identifying the schema versions and every payload.

Source photographs, thumbnail and remote preview caches, credential files, logs and unregistered files are excluded. The copied catalog also removes the `google_credentials_path` setting. Original photographs require a separate backup under your control. The catalog still contains private metadata such as source paths, notes and discovered URLs, so protect the bundle as you protect your catalog. No upload is performed.

Before publishing the new bundle, maintenance verifies payload hashes and sizes, referenced artifact coverage, SQLite readability/integrity, foreign keys and supported schema versions. Missing or altered artifacts, insufficient space and filesystem errors fail the operation. The output directory appears only after successful verification; an existing output is never replaced. Hashes detect corruption, but are not a signed authenticity guarantee against an attacker who can replace both payloads and manifest.

A killed process or power loss can leave a sibling `.pp-staging-*` directory. It is never a completed backup or restored profile, and maintenance does not resume or garbage-collect it automatically. After stopping the app and maintenance processes, inspect the exact staging directory created for the interrupted operation and remove it manually if no longer needed. Retry with a new output directory; never rename an incomplete staging directory into a published bundle.

## Restore into a fresh profile

Stop Photo Privateer before switching profiles. Restore into a directory that does not exist, keeping the previous profile and the bundle intact:

```powershell
python -m backend.maintenance restore "D:\PhotoPrivateerBackups\2026-10-04" --profile "D:\PhotoPrivateerRecovered"
$env:PHOTO_PRIVATEER_DATA_DIR = "D:\PhotoPrivateerRecovered"
python start.py
```

Restore verifies the bundle first, copies into a private staging directory and checks the copied payloads before publishing the new profile. It never replaces an existing profile. Unsupported newer schema or bundle versions are rejected; use a compatible Photo Privateer release. Starting the recovered profile may apply this release's pending migrations, after a verified pre-migration snapshot. Startup also performs the normal interrupted-scan recovery and group repair. Check the recovered libraries and review history before adopting the new profile. If needed, stop the app and point `PHOTO_PRIVATEER_DATA_DIR` back to the previous profile. Credentials must be configured separately; thumbnails are regenerated as needed.

## Reconnect a renamed or moved library

Restoring a catalog preserves recorded library roots. If originals are now at another root, stop the server and use the existing numeric library ID shown in the library API response. First validate without applying:

To identify the library before stopping the app, run `Invoke-RestMethod http://127.0.0.1:8765/api/libraries | Select-Object id, name, path` while it is open. Then stop it and use that ID below.

```powershell
python -m backend.maintenance relink --profile "D:\PhotoPrivateerRecovered" --library-id 3 --new-root "E:\Photos\Portfolio"
python -m backend.maintenance relink --profile "D:\PhotoPrivateerRecovered" --library-id 3 --new-root "E:\Photos\Portfolio" --apply
```

Dry run is the default. Relinking maps indexed relative paths under the new root and validates the SHA-256 of every present source. Missing files remain recorded as unavailable; a different file at an indexed path is an error. Overlapping libraries, path collisions and escaped paths are rejected. Historical archived path aliases remain historical aliases. Relinking preserves IDs, hashes, groups, projects, discoveries and review history; it does not choose identities by a duplicate-hash heuristic. No original is written, moved or renamed.

Applying first creates a verified recovery bundle under the profile's `backups` directory, then changes the library root and indexed paths atomically. A profile lease refuses relinking while the app is running. After applying, start the app on that profile and check availability before scanning.

## Migration recovery

Before the first pending migration mutates an existing catalog, initialization creates and verifies a bundle under `backups/pre-migration-*`. A failed backup aborts migration; an up-to-date or new catalog does not need a pre-migration snapshot. Keep these snapshots until the new release and review history are verified. They also provide the recovery gate for later identity migrations.

If a migration fails, stop the app, verify the pre-migration bundle and restore it into another fresh profile using the commands above. Keep the failed profile for diagnosis. Use a compatible release or a corrected migration before launching the restored profile; simply launching the same failing release may reproduce the failure. Recovery never writes over the failed or previous catalog.

## Managed artifact contract for future features

Migration 021 adds the shared registry; it does not implement evidence capture or cases. Future owner tables must reference `catalog_artifacts.id` using `ON DELETE RESTRICT`. Publish a new immutable blob under `artifacts/` before committing its metadata and owner reference in the same catalog transaction. Use a fresh UUID for its ID, a canonical relative POSIX path, a lowercase SHA-256, exact byte size and the appropriate kind. Registered metadata cannot be updated; a replacement is a new artifact. Symlinks, junctions, hardlinks, credentials and files under original library roots are forbidden. A backup includes all registered blobs, and refuses completion when any reference is missing or altered. Unregistered staging files are excluded; future cleanup must never remove a referenced blob.
