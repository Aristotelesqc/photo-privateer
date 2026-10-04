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
| 5 | #28 deterministic API contract checking | Planned |
| 6 | #25 active-library browsing and scan eligibility | Planned |
| 7 | #30 durable photo identity contract | Planned before WebUse schema work |
| 8 | #48 verified backup/recovery | Required before #33 migration |

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
