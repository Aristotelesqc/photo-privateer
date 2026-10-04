# AGENTS.md — Photo Privateer Developer & Operational Handbook

Photo Privateer is a local desktop web application for professional photographers to periodically detect unauthorized reuse of their photographs on the public web using reverse image search.

---

## 0. Non-Negotiable Invariants

1. **User-Controlled Scanning Only**: Never invoke paid or search APIs automatically. No background daemons, scheduled cron tasks, or polling loops. Scanning occurs solely upon explicit user interaction.
2. **Source Image Integrity**: Never modify, overwrite, move, or rename original source photographs on disk. Filesystem access to user images is strictly read-only.
3. **Local-First & Private**: SQLite and the local filesystem are canonical. The backend binds strictly to `127.0.0.1`. No telemetry, analytics, remote Photo Privateer backend, or cloud database.
4. **Transparent Cost Estimates**: Locally tracked API usage figures and costs are estimates based on Google Cloud Vision Web Detection published rates ($3.50 per 1,000 units above free tier). Prominently distinguish local estimates from authoritative Google billing statements.
5. **Deterministic Offline Capability**: The entire system must function and be testable offline using the built-in deterministic Mock Provider without requiring Google credentials.
6. **No Fake Controls**: Every interactive element, button, and filter must function end-to-end. Non-interactive items must never pretend to be clickable.
7. **Zero Scope Erosion**: Do not omit requirements, weaken safety constraints, or leave unfulfilled TODOs.
8. **Non-Destructive Archiving**: Archiving a library retains all indexed photo metadata and review match triage records. Photos and matches are never deleted unless explicitly purged.
9. **Cooperative Scan Cancellation & Crash Recovery**: In-progress scans can be cooperatively cancelled via flag checks between images. Any sessions left `RUNNING` due to an unexpected process termination are recovered to `INTERRUPTED` on startup.
10. **Isolated Worktree & Synchronized PR Head Description**: Never commit directly to `main` or push directly to `main`. All modernization passes, bug fixes, feature additions, and audit remediations must be developed inside an isolated Git worktree on a dedicated feature branch and submitted as an open GitHub Pull Request targeting `main`. Every subsequent push or modification to a PR branch must synchronously update the PR's head description (`gh pr edit`) to document the current commit state, test metrics, and resolved audit findings.

---

## 1. What Photo Privateer Is

- A focused personal desktop monitoring tool for one local user on Windows.
- A non-destructive local indexer for photograph libraries (JPEG, PNG, WebP, TIFF).
- A reverse image search runner (Google Cloud Vision Web Detection & Mock Provider).
- A persistent SQLite-backed registry of web discoveries with classification and note-taking workflows.
- A domain-rules engine that automatically filters known scrapers or authorized client portfolios.
- A transparent local API cost estimator and safety guard preventing quota overruns.

---

## 2. What Photo Privateer Is Not

- NOT a continuous background web crawler or scraping bot.
- NOT a multi-tenant SaaS application or cloud service.
- NOT a legal recovery or copyright infringement enforcement agency.
- NOT an image editor, digital asset manager (DAM), or catalog replacement.
- NOT an authentication or user account platform.

---

## 3. Technology Stack

- **Backend**: Python 3.14, FastAPI, Uvicorn, SQLite3 (WAL mode), Pydantic v2, Pillow.
- **Frontend**: React 19, TypeScript 7, Vite 8, Tailwind CSS v4 (@tailwindcss/vite, CSS-first architecture, Lightning CSS), Lucide React icons.
- **Integration**: Google Cloud Vision client library (`google-cloud-vision`) with Application Default Credentials (ADC) and zero-cost credential testing.
- **Testing**: pytest for Python; Vitest for frontend unit tests; Playwright for end-to-end browser validation.
- **Runtime Topology**: Single process local server. FastAPI serves both the JSON REST API (`/api/*`) and the compiled Vite static assets (`/` and `frontend/dist`).


---

## 4. Repository Map

```text
photo-privateer/
├── AGENTS.md                      # Operational and architectural handbook
├── README.md                      # User setup, architecture, and launch guide
├── START_PHOTO_PRIVATEER.bat      # Windows double-click launcher
├── start.py                       # Python entry point and browser bootstrap
├── setup.ps1                      # PowerShell first-run environment installer
├── requirements.txt               # Python package dependencies
├── .gitignore                     # Excludes caches, DBs, node_modules, and secrets
├── backend/
│   ├── main.py                    # FastAPI app, static SPA mount, lifespan startup recovery
│   ├── config.py                  # User data paths, 127.0.0.1 binding, pricing constants
│   ├── database.py                # SQLite connection, WAL mode, migration initialization
│   ├── models.py                  # Pydantic schemas and dataclasses
│   ├── migrations/                # Versioned schema migrations
│   │   └── runner.py              # Idempotent migration runner & applied tracker (001 through 020)
│   ├── repositories/              # Data access layer (libraries, images, matches, rules, usage, settings)
│   ├── services/                  # Indexer, thumbnail cache, image service, rules, scan engine
│   ├── providers/                 # Base provider interface, Mock provider, Google Vision provider
│   └── api/                       # Modular FastAPI routers (/api/libraries, /api/photos, /api/scans, etc.)
├── frontend/
│   ├── package.json               # Node dependencies (@tailwindcss/vite, tailwindcss v4)
│   ├── vite.config.ts             # Vite build configuration with @tailwindcss/vite plugin
│   ├── vitest.config.ts           # Vitest unit test configuration
│   ├── playwright.config.ts       # Playwright E2E configuration with auto webServer management
│   ├── e2e/                       # Playwright browser end-to-end test suite
│   ├── src/
│   │   ├── main.tsx               # React DOM root mount
│   │   ├── App.tsx                # Navigation and top-level state
│   │   ├── types/index.ts         # TypeScript interfaces
│   │   ├── api/client.ts          # Typed API client
│   │   ├── styles/                # Modular Tailwind 4 CSS layers (theme.css, utilities.css, base.css)
│   │   ├── components/
│   │   │   ├── blocks/            # Reusable atomic UI blocks (ProjectBadge, StatusPill, FilterSelect)
│   │   │   └── ...                # Header, Thumbnail, Modal dialogs (ScanProgressModal, etc.)
│   │   ├── engines/               # Domain-driven feature engines
│   │   │   ├── library/           # LibraryFilterBar, PhotoCard, ProjectAssignModal
│   │   │   ├── review/            # ReviewFilterBar, MatchCard, MatchInspectModal
│   │   │   └── settings/          # MonitoredFolderCard, AddFolderSection
│   │   ├── views/                 # Lean declarative view coordinators (LibraryView, ReviewView, SettingsView, UsageView)
│   │   └── __tests__/             # Frontend unit tests for blocks, engines, and modals (Vitest)
├── tests/
│   └── backend/                   # Unit, integration, and resilience test suite (pytest)
└── .agents/
    └── skills/
        ├── verify-photo-privateer/# Reusable quality audit skill
        ├── bump-version/          # Automated version bump and release workflow skill
        └── worktree-pr/           # Isolated Git worktree and Pull Request workflow skill
```

---

## 5. Architectural Boundaries

```text
React UI (SPA)
   ↓ REST / JSON
FastAPI HTTP Layer (127.0.0.1:8765)
   ↓
Photo Privateer Core Services
   ├── LibraryIndexer (Read-only filesystem scanner, SHA-256)
   ├── ThumbnailCache (Pillow WebP cache in ~/.photo_privateer/thumbnails)
   ├── ImageService (Strict containment validation against registered libraries)
   ├── DomainRulesEngine (Subdomain-aware normalization and auto-classification)
   ├── UsageTracker (Google Vision unit accounting and cost estimator)
   ├── MigrationRunner (Idempotent schema version transitions)
   └── ScanEngine (Asynchronous batch coordination, cancellation checks, match normalization)
   ↓
Persistence Layer
   ├── SQLite Repositories (~/.photo_privateer/photo_privateer.sqlite)
   └── SearchProvider Abstraction
         ├── MockSearchProvider (Deterministic offline edge cases)
         └── GoogleVisionSearchProvider (Official Cloud Vision Web Detection & ADC)
```

---

## 6. Data Invariants

1. **Source Photos Unmodified**: Indexing and thumbnail generation access original files in read-only binary mode.
2. **Rescan History Preservation**: Rediscovering a previously known match updates `last_seen_at`, but NEVER wipes the user's classification (`APPROVED`, `UNAUTHORIZED`, `IRRELEVANT`), manual notes, or creates duplicate rows.
3. **New Discoveries Identifiable**: Newly discovered matches are flagged with `is_new = 1` until acknowledged.
4. **Domain Rule Provenance**: Matches auto-classified by a domain rule store `auto_classified_by_rule_id`. A manual classification override by the user clears this rule reference and is permanently respected on subsequent scans.
5. **Path Traversal Protection**: Photo streaming endpoints strictly verify that the requested file resolves within an active, enabled library root using `os.path.commonpath`.
6. **Library Archival Integrity**: Archiving sets `is_archived = 1` and excludes the library from scanning without deleting photo records or match reviews.
7. **Disk Presence Tracking**: If a library or folder is temporarily unmounted or missing on disk, `is_present_on_disk = 0` reflects reality without losing indexed data. Reconnection cleanly restores `is_present_on_disk = 1`.
8. **Session Resilience**: Interrupted or crashed scans automatically recover to `INTERRUPTED` on startup.
9. **Project Assignment Preservation**: Manual project assignments made by the user in the UI are permanently respected. Re-indexing existing images uses SQLite `COALESCE(images.project, excluded.project)` to preserve manual overrides, while subfolder auto-detection assigns immediate parent folders on newly discovered images.
10. **Perceptual Source Grouping & Scan Deduplication**: Visual representations of the same photograph (detected via 64-bit dHash with Hamming distance <= 10) can be grouped by the user without altering individual photo metadata or original files. Each group designates a preferred primary representation (`is_primary_representation = 1`), and batch scan operations strictly deduplicate grouped representations so that exactly one reverse image search call is dispatched per group per scan operation. Discoveries are recorded once per group: match identity on rediscovery spans all current group members, so changing the primary (or falling back to another member) updates the existing discovery and preserves its triage; when photos become one identity (group creation, joining a group, validated re-export lineage) their duplicate discoveries are folded, never deleted (migration 011): every `matches` row stays as a physical observation, one row per identity is the logical discovery shown and counted (`canonical_match_id IS NULL`, earliest first seen, latest last seen, notes and acknowledgement merged), folded observations keep their own original triage as read-only provenance (`GET /api/matches/{id}/observations`); a row that carries a logical discovery first keeps its own original triage in `obs_*` columns (migration 012, exposed as `observed_classification` / `observed_notes`); a provider hit on a group member that has no row for an already-known web use records that member's own folded observation. Conflicting reviewed classifications are never resolved silently: the logical discovery returns to UNREVIEWED with a note listing the previous decisions and is marked `triage_conflict` (migration 013); the mark survives further merges and domain rules and is cleared only by an explicit classification. Folding is reversible: ungrouping rolls each photo back to its state right before that grouping cycle (`rb_*`, captured at the start of each cycle, migration 016; distinct from the immutable original observation in `obs_*`, so a later cycle never undoes a decision made after an earlier one), and a former canonical discovery rolls back unless the user explicitly reviewed the logical discovery (any classification, acknowledgement or notes action through the API, `explicit_review_at`, migration 014) after it began carrying merged state (`merged_at`, which travels with handovers), in which case that decision stays and the original triage remains provenance; when the photo holding a logical discovery leaves its group or is purged, the logical triage is handed over to a remaining member's observation. Purging a grouped photo never loses the group's discoveries: a promoted observation, or a discovery re-homed to a surviving member (present in an active library first, then the primary, then the lowest id) when no member observed it, is marked as inherited (`inherited_at` / `inherited_from`, migration 015) and keeps its logical triage instead of restoring an observation's original one, including when that row later leaves another group as a folded observation; inheritance travels with the logical discovery through later handovers and coalescence, keeping every original purged source. Only inheritance acquired during the current cycle (a purge after the cycle began, `inherited_at` later than `merged_at`) blocks the rollback; inheritance that existed before a later reversible grouping is part of its rollback state (`rb_inherited_*`, migration 017) and is restored with it. The rollback state also keeps an unresolved conflict that predates the cycle (`rb_triage_conflict`, migration 018), so a reversible grouping never lets a domain rule resolve it. Only active GROUP observations keep a grouping cycle open: permanent re-export provenance (LINEAGE) never does, and a validated re-export merge does not open a reversible cycle; when a merged discovery is already in an open grouping cycle (a group head is re-exported), the cycle carries over with a rollback state combining the permanent lineage decisions without the temporary group merge. Migrations 019 and 020 backfill the conflict flag of rollback states captured before migration 018 conservatively: an unreviewed snapshot whose discovery is still in conflict is an unresolved conflict (editable note text is never used as evidence that there was none). Migration 018 closes cycles that ended before migration 016 (obsolete `merged_at` / `explicit_review_at` on independent discoveries). Repeated conflicts keep a single banner listing the union of previous decisions. `scan_count` / `last_scanned_at` are physical per-file history (never written to siblings); group coverage is derived (MAX over members). Scan planning resolves availability per group (a missing selected member is searched through an available one). Library filters (matches, unreviewed, scanned/unscanned coverage), card counts, the per-photo review view, project filtering of discoveries and the original preview (`display_image_id`, restricted to present photos in active libraries) are group-aware. Exact-duplicate candidates are linear per SHA cluster, only one representative per SHA cluster enters the perceptual pass, and pairs of two grouped photos are never compared. Group integrity is repaired at the end of every index pass and at startup. Selected photos covered by the search of another photo in their group are reported in the scan projection and session notes; a photo grouped while a scan is running, when another current member of its group was already searched successfully in that session (grouped before, during or after that search), is recorded as a `SKIPPED` scan item without a provider call. Adding a photo to an existing group never changes the group's primary unless the user explicitly picks one. Re-exporting a grouped photo in place (new content, same path) preserves its group membership, primary role and discoveries only when the new content is perceptually a re-export of the old one (same candidate threshold); an unrelated photo reusing the path stays ungrouped. Images with transparency are composited onto a white matte before hashing (hidden RGB under transparent pixels never affects the dHash). Low-information dHashes (near-uniform frames) are excluded from perceptual matching; the perceptual pass keeps at most `MAX_CANDIDATES_PER_PHOTO` candidates per photo so dense burst clusters stay bounded in work and memory, and `CANDIDATE_COMPARISON_BUDGET` is a hard ceiling enforced at each comparison (large false-positive buckets included), and the candidates API (`limit`/`offset`) reports `truncated` when the cap or comparison budget was reached (the UI shows "N+"); creating a library also invalidates the candidate cache; candidate search uses exact pigeonhole band bucketing and is cached until a trigger-maintained generation counter (migration 010) changes.

---

## 7. Search Provider Contract

All search integrations must implement `SearchProvider` (`backend/providers/base.py`):
```python
class SearchProvider(abc.ABC):
    def search(self, image_path: str, **kwargs) -> ProviderResult: ...
```
- Results are normalized into `SearchResultItem` records containing `page_url`, `domain`, `match_type`, `page_title`, `page_score`, and `candidate_image_url`.
- URL normalization strips marketing trackers (`utm_*`, `fbclid`) and trailing slashes while preserving the resource path.
- Provider errors must return `ProviderResult(success=False, error_message=...)` without throwing unhandled exceptions.

---

## 8. Security and Credentials

- Google Service Account JSON files must never be committed to git, uploaded to browser storage, or logged.
- The Settings UI accepts and validates the local file path on disk; the secret payload never leaves the Python backend.
- **Fast ADC Check**: In local desktop environments, never invoke `google.auth.default()` blindly without pre-checking local ADC credential file existence (`%APPDATA%/gcloud/application_default_credentials.json` on Windows, `~/.config/gcloud/application_default_credentials.json` on Linux/macOS), preventing 20–30s link-local metadata ping hangs on consumer networks.
- **Zero-Cost Auth Verification**: Validate Google Cloud credentials strictly via OAuth2 token refresh (`credentials.refresh(Request())`) against Google's token endpoint rather than issuing paid Cloud Vision Web Detection calls. This validates OAuth2 credential validity and token retrieval at $0.00 cost with 0 API quota consumed (note: this verifies credentials and token refresh against Google's auth endpoint; it does not assert that the Cloud Vision API is enabled, Web Detection is authorized, or Cloud Billing is active).
- Remote candidate match images are loaded directly in the user's browser with `referrerpolicy="no-referrer"` upon user opt-in.
- The server binds strictly to `127.0.0.1`.

---

## 9. UX & Design Principles

- **Professional Photography Aesthetic**: Elegant dark/neutral theme (`carbon-950` to `carbon-800`), restrained typography, generous spacing, image-first presentation.
- **Efficient Match Review**: Discoveries are presented with side-by-side original and found thumbnails, quick classification buttons, direct link to live web pages, inline notes, and a high-resolution inspection modal.
- **Intentional States**: Explicit empty states, loading skeletons, progress modals, and error boundaries for all views.

### 9.1 Engines and Blocks Architecture
- **Lean View Coordinators**: Top-level views (`LibraryView`, `ReviewView`, `SettingsView`, `UsageView`) must remain lean coordinators focused on top-level state and API orchestration, delegating presentation and composite controls to `src/engines/`.
- **Atomic Blocks Purity**: Reusable UI atoms reside in `src/components/blocks/` (`ProjectBadge`, `StatusPill`, `FilterSelect`) with strict TypeScript typing and zero parent state leakage.
- **Zero `any` Standard**: Avoid loose `any` types in error handling and state; use explicit narrowing (`err instanceof Error ? err.message : String(err)`).

### 9.2 Tailwind CSS v4 Theme Completeness Invariant
- **Exhaustive Color Stops**: In Tailwind v4, custom palettes declared in `@theme` (such as `carbon` and `accent`) do not automatically inherit undeclared numeric stops. All required shade stops (e.g. `accent-100` through `accent-950`) must be explicitly declared in `src/styles/theme.css` to prevent silent CSS rule omission.
- **Custom Utility Directives**: Extended interactive utilities (`scale-98`, `backdrop-blur-xs`, `shadow-xs`, `tabular-nums`) must be maintained via native `@utility` blocks in `src/styles/utilities.css`.


---

## 10. Testing & Verification

Verification follows a strict 4-tier testing hierarchy:
1. **Tier 1 - Backend Tests**: `pytest -v tests/backend` (Unit, integration, migrations, archiving, cancellation, recovery, ADC auth).
2. **Tier 2 - Frontend Unit Tests**: `npm test` inside `frontend/` (Vitest component testing for thumbnails, scan modal, confirm dialogs).
3. **Tier 3 - Frontend Production Build**: `npm run build` inside `frontend/` (TypeScript verification and bundle emission).
4. **Tier 4 - Playwright End-to-End Suite**: `npm run test:e2e` inside `frontend/` (Full headless browser validation of complete user journeys).

### 10.1 Playwright Server Lifecycle Invariant
- **Isolated Test Instance**: In `playwright.config.ts`, always configure `reuseExistingServer: false`. Reusing background server processes silently masks backend schema changes, routing updates, or stale frontend bundle artifacts. Every test suite execution must launch a fresh process running current working tree code.

---

## 11. Git Identity & Remote Publishing Invariant

1. **Pre-Commit Account Alignment**: Before creating an initial commit or pushing to a remote host (e.g., GitHub), always verify that `git config user.name` and `git config user.email` match the target repository owner and active GitHub CLI session (`gh auth status`).
2. **Contributor Graph Protection**: Never allow unconfigured machine credentials or local defaults to generate commits on newly initialized user repositories, preventing attribution pollution in GitHub's contributor statistics.

---

## 12. Dependency & Runtime Modernization Policy

1. **Canonical Runtimes**: The supported canonical runtime baseline is **Python 3.14** and **Node.js 24 LTS** (build/test/dev). Python 3.11+ is supported on a best-effort compatibility fallback basis. Node is not required at runtime after production frontend assets are compiled.
2. **Current Stable Baseline**: Prefer the current stable release line for direct runtimes, frameworks, libraries, build tools, and test tooling. Do not retain an older major solely for conservatism or historical compatibility. A deliberate stable-version holdback requires a concrete demonstrated incompatibility, upstream regression, unsupported runtime, or failing project test and must be documented. Pre-release, beta, RC, canary, and nightly versions are excluded by default.
3. **Exact Direct Declarations**: Direct dependencies are declared as explicit verified versions in `requirements.txt` / `requirements-dev.txt` and `frontend/package.json` to guarantee local and CI reproducibility.

---

## 13. Isolated Worktree & Pull Request Workflow Invariant

1. **Protected Main**: `main` is strictly protected against direct pushes and direct commits.
2. **Worktree Isolation**: All development work must be executed in a dedicated worktree under `../photo-privateer-worktrees/<branch-name>` on a dedicated branch (e.g., `git worktree add ../photo-privateer-worktrees/<branch-name> -b <branch-name> origin/main`).
3. **Pull Request Delivery**: Changes are submitted via `gh pr create --base main --head <branch>` and left OPEN for independent review. Never merge automatically.
4. **Synchronized PR Head Description Invariant**: Every push or modification made to a PR branch must synchronously update the PR's head description (`gh pr edit <pr-number> --body ...`) so that the PR summary on GitHub always reflects the latest commits, architectural changes, and updated verification metrics.


