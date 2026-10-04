# MVP implementation progress

Baseline: PR #4 merged into main at `98a71a9` (2026-10-04). Roadmap #13
remains the delivery index. This branch delivers small validated slices in one
open PR; an implemented slice is not considered delivered on main until merge.

| Order | Issue | Status |
| --- | --- | --- |
| 1 | #23 global loopback Host validation | Implemented; local four-tier verification |
| 2 | #24 reference-aware thumbnail purge | Implemented; local four-tier verification |
| 3 | #27 atomic concurrent thumbnail generation | Planned; follows #24 |
| 4 | #26 index/scan coordination | Planned |
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
