# Active monitoring and historical browsing

The Library view starts with enabled, non-archived libraries. The visible
**Include archived / disabled** checkbox includes historical sources and saves
the preference locally across reloads. Turning it off clears an inactive library
filter. Archiving never removes photos, discoveries, classifications or notes;
the Review view continues to expose historical discoveries.

Photo browse/detail responses expose `library_enabled`, `library_archived`,
`source_available` and `scan_eligible`. These are computed snapshots, not stored
permissions; other catalog/group responses leave these optional snapshots null.
Listings and project filters use `include_inactive=false` by default. Repository
history access retains all sources unless explicitly asked for active sources.

| Selected representation | Source used for a scan | Selectable |
| --- | --- | --- |
| Active, available, ungrouped | That file | Yes |
| Active, grouped | Available active preferred member, selected member, then other member | Yes if any eligible member exists |
| Active, missing, grouped | An available active sibling | Yes; labelled Missing and Search via group |
| Active, missing, ungrouped or group with no available active member | None | No |
| Archived or disabled, with or without an active sibling | None for that selection | No; historical review remains available |

Availability requires an indexed-present regular file whose resolved path lies
inside its registered library root. Archived/disabled members do not hide an
active group or erase its aggregate discoveries. Group scan counts and discovery
counts continue to include retained history from all representations.

Single selection, select-all and batch project assignment use this policy.
Preparation and launch validate fresh catalog state; the worker rechecks sources
before each provider call. If monitoring changes after selection, refresh the
selection or enable/unarchive the library in Settings. The UI refreshes after a
rejected preparation or launch. Browse snapshots cannot guarantee that a drive
will remain connected; the confirmation remains the final server projection.

No original file is changed, and no scan starts automatically.
