# MVP implementation progress

Baseline: PR #4 merged into main at `98a71a9` (2026-10-04). Roadmap #13
remains the delivery index. This branch delivers small validated slices in one
open PR; an implemented slice is not considered delivered on main until merge.

| Order | Issue | Status |
| --- | --- | --- |
| 1 | #23 global loopback Host validation | Implemented; local four-tier verification |
| 2 | #24 reference-aware thumbnail purge | Implemented; local four-tier verification |
| 3 | #27 atomic concurrent thumbnail generation | Implemented; local four-tier verification |
| 4 | #26 index/scan coordination | Implemented; local four-tier verification |
| 5 | #28 deterministic API contract checking | Implemented; local four-tier verification |
| 6 | #25 active-library browsing and scan eligibility | Implemented; local four-tier verification |
| 7 | #30 durable photo identity contract | Reviewed ADR and executable PR4 examples; no target schema installed |
| 8 | #48 verified backup/recovery | Implemented; local four-tier verification and independent review |

## Slice 1 — #23

- Validate the raw Host header before API, original-file, thumbnail, static and
  SPA routing, including CORS preflights. Reject missing/duplicate headers,
  arbitrary names, invalid ports and deceptive loopback representations.
- Forwarded headers do not influence the boundary. Existing mutation
  Origin/Referer and cross-site protections remain, using the same strict local
  authority parser; synthetic test hosts are confined to tests.
- Tests use isolated databases and deterministic mock providers. Local runtime:
  Python 3.13.14 compatibility fallback and Node 24.19.0. CI tests canonical
  Python 3.14 and Node 24 on Linux, plus the Windows smoke workflow.
- Local verification: backend 215 passed; frontend 51 passed; production build
  and Playwright 8 scenarios passed. No paid search calls or original writes.

Delegated explorations follow Arete's sub-explore contract: read-only, cited
facts, root verification before writes. Delegated verdicts are separate reviews.
External AGY repository exploration awaits the explicitly requested private-code
transmission authorization; local implementation and verification can proceed.

## Slice 2 — #24

- A committed purge removes only thumbnails without any surviving image
  reference, including archived, disabled and offline libraries. Hashes are
  deduplicated. A SQLite `BEGIN IMMEDIATE` reservation covers reference checking
  and eviction so another catalog writer cannot insert between them.
- A rolled-back purge leaves thumbnails alone. Cache deletion failures are
  logged after the database commit and do not report a fictitious purge rollback.
- Eleven focused regressions cover both purge orders, all surviving library
  states, final-reference eviction, rollback, filesystem failure and a competing
  SQLite writer at the eviction boundary.
- Local verification: backend 226 passed; frontend 51 passed; production build
  and Playwright 8/8 passed. Same isolated mock/runtime baseline as slice 1.

## Slice 3 — #27

- Unique temporary files in the cache, closed before encoding on Windows,
  published with atomic replacement and removed after normal failures.
- One process-wide reentrant cache lock bounds coordination state and serializes
  generation, eviction and response snapshots. Different hashes are serialized
  deliberately for the single-user desktop workload. The existing provider
  scan/group semantics do not change.
- HTTP thumbnail responses snapshot encoded bytes under the lock, so deletion
  after the snapshot cannot break a successful response. A request arriving
  after eviction can regenerate only through a validated original path; an
  unavailable/purged source returns the existing not-found behavior. Generation
  after a catalog purge can leave a harmless unreferenced cache entry; it never
  resurrects catalog rows or writes originals.
- Abandoned cleanup inspects at most 128 entries and deletes at most 16 owned
  temporary files older than a day, without following symlinks. SHA cache keys
  and resolved cache paths are validated.
- Ten focused regressions cover concurrency, unique publication, encode/replace
  failure, cleanup limits, response/purge interleaving, orientation and alpha.
- Local verification: backend 236 passed; frontend 51 passed; production build
  and Playwright 8/8 passed.

## Slice 4 — #26

- A per-database coordinator reserves indexing and scans atomically across
  request/service instances and connections. The reservation covers a whole
  synchronous scan or transfers to the background worker until it exits.
- Index/project detection refuses persisted RUNNING sessions; scan preparation
  refuses an active index. API conflicts return 409 with retry/cancel guidance
  already displayed by the UI's error/feedback paths. Group edits during scans
  retain their existing supported semantics.
- Index exceptions rollback outstanding work and release reservations. Launch
  failures mark their created session FAILED. Worker bootstrap failures release
  reservations and attempt durable failure recording. Cancellation releases only
  after the worker exits. Reservations live in memory, while existing startup
  recovery marks previous-process RUNNING sessions INTERRUPTED.
- Ten deterministic tests cover both start orders, a barrier-controlled
  simultaneous start, independent connections, exceptions, launch/worker failure,
  cancellation, 409 responses and startup recovery; no timing sleeps.
- Local verification: backend 246 passed; frontend 51 passed; build and
  Playwright 8/8 passed.

## Slice 5 — #28

- Commit a deterministic OpenAPI snapshot and generated TypeScript schemas and
  operation contracts. API responses now expose their actual required default
  fields; clients derive payloads, queries and results from these contracts.
- CI checks server-side drift without rewriting artifacts. The bounded Python
  generator rejects unsupported schema shapes; its rationale and regeneration
  commands are documented in docs/API_CONTRACT.md. The upstream generator's
  TypeScript 5 peer constraint conflicts with this repository's TypeScript 7.
- Contract regressions cover backend-only drift, nullable fields, acknowledgement
  without changing classification, missing-photo filters, paging and errors.
- Local verification: backend 250 passed; frontend 54 passed; build and
  Playwright 8/8 passed; generated-contract check passed.

## Slice 6 — #25

- Active libraries and projects are the default; an explicit, visible checkbox
  persistently includes archived/disabled sources. Historical discoveries and
  notes remain available. Cards label archival, disabled monitoring and missing
  sources, with accessible selection controls disabled where appropriate.
- Browse/detail eligibility and scan planning share containment/file availability.
  Missing active group members can use eligible siblings; inactive selections
  cannot. Select-all and batch assignment follow the same policy. Preparation,
  launch and workers revalidate; failures provide Settings/refresh guidance.
- Current availability powers the Missing filter before counts/pagination.
  Project contexts reset hidden filters and ignore stale responses. Seven backend
  regressions, six added component/view regressions and an E2E recovery scenario
  cover archival, disabling, offline sources, groups, selection and history.
- Independent local review findings were verified and fixed. The binary original
  download contract from slice 5 now explicitly declares Blob responses.
- Local verification: backend 257 passed; frontend 60 passed; build and
  Playwright 9/9 passed; generated-contract check passed.

## Slice 7 — #30

- Reviewed identity ADR separates stable photograph/representation identities,
  historical mutable groups, reversible GROUP equivalence and permanent LINEAGE.
  It defines every transition, scope snapshots, provenance, conditional cycle
  restoration, handovers, tombstones and RESTRICT deletion behavior.
- The target WebUse key follows #31: durable photograph + conservative page;
  rotating assets stay subordinate and ASSET_ONLY associations remain reversible.
  The legacy triple remains a compatibility key, not the target identity.
- Nine executable legacy scenarios (ten tests) verify real SQLite transitions,
  source-byte integrity and FK checks. A split-equivalent example preserves
  inherited projections without creating new explicit decisions or scopes.
- Root validated delegated outputs and independent review corrections. Legacy
  provenance gaps are explicit; no UUID schema or future case/evidence feature
  is claimed installed. Backup/recovery #48 precedes dependent migration.
- Local verification: backend 267 passed; frontend 60 passed; build and
  Playwright 9/9 passed; generated-contract check passed.

## Slice 8 — #48

- Explicit offline maintenance commands create consistent SQLite/WAL bundles,
  verify hashes/schema/foreign keys, restore to a fresh profile and relink moved
  library roots without replacing identities or modifying original photographs.
- Versioned manifests cover the database and all immutable managed artifacts.
  Migration 021 provides the shared evidence/case-attachment registry; future
  capture/case features remain separate. Credentials, source originals, previews,
  logs and unregistered files are excluded. Recovery instructions are in
  docs/BACKUP_RECOVERY.md; source photos require their own backup.
- Existing catalogs receive a verified backup before any pending migration;
  failed backup aborts upgrade. Relink applies only after a verified backup and
  transaction revalidation. OS profile ownership prevents live migrations/relink
  and remains held until catalog workers finish, even on shutdown failure/cancel.
- Root validated delegated implementation, tests and independent review. Tests
  demonstrate full historical row recovery, live WAL/read activity, writer
  reservation, relocated/missing/duplicate sources, failure cleanup, publication
  races, credentials exclusions, schema corruption and interprocess locking.
- Local verification: backend 346 passed, 3 symlink tests skipped for Windows
  permissions (a real Windows junction escape test passed); frontend 60 passed;
  build, generated-contract check and Playwright 9/9 passed. Linux CI exercises
  symlink paths on the canonical Python 3.14 runtime.
- Next: #31 WebUse identity, #32 append-only observations and #34 decision
  semantics prepare #33 legacy migration using this recovery gate.
