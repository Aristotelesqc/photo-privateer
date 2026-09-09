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

- **Backend**: Python 3.11+, FastAPI, Uvicorn, SQLite3 (WAL mode), Pydantic v2, Pillow.
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, Lucide React icons.
- **Integration**: Google Cloud Vision client library (`google-cloud-vision`).
- **Testing**: pytest & pytest-asyncio for Python; Playwright/Vitest for frontend/browser validation.
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
│   ├── main.py                    # FastAPI app, static SPA mount, lifespan
│   ├── config.py                  # User data paths, 127.0.0.1 binding, pricing constants
│   ├── database.py                # SQLite connection, WAL mode, migrations
│   ├── models.py                  # Pydantic schemas and dataclasses
│   ├── repositories/              # Data access layer (libraries, images, matches, rules, usage)
│   ├── services/                  # Indexer, thumbnail cache, image service, rules, scan engine
│   ├── providers/                 # Base provider interface, Mock provider, Google Vision provider
│   └── api/                       # Modular FastAPI routers (/api/libraries, /api/photos, etc.)
├── frontend/
│   ├── package.json               # Node dependencies
│   ├── vite.config.ts             # Vite build configuration and dev proxy
│   ├── src/
│   │   ├── main.tsx               # React DOM root mount
│   │   ├── App.tsx                # Navigation and top-level state
│   │   ├── types/index.ts         # TypeScript interfaces
│   │   ├── api/client.ts          # Typed API client
│   │   ├── components/            # Header, Thumbnail, Modal dialogs
│   │   └── views/                 # LibraryView, ReviewView, UsageView, SettingsView
├── tests/
│   └── backend/                   # Unit and integration test suite
└── .agents/
    └── skills/
        └── verify-photo-privateer/# Reusable quality audit skill
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
   └── ScanEngine (Batch coordination, provider dispatch, match normalization)
   ↓
Persistence Layer
   ├── SQLite Repositories (~/.photo_privateer/photo_privateer.sqlite)
   └── SearchProvider Abstraction
         ├── MockSearchProvider (Deterministic offline edge cases)
         └── GoogleVisionSearchProvider (Official Cloud Vision Web Detection)
```

---

## 6. Data Invariants

1. **Source Photos Unmodified**: Indexing and thumbnail generation access original files in read-only binary mode.
2. **Rescan History Preservation**: Rediscovering a previously known match updates `last_seen_at`, but NEVER wipes the user's classification (`APPROVED`, `UNAUTHORIZED`, `IRRELEVANT`), manual notes, or creates duplicate rows.
3. **New Discoveries Identifiable**: Newly discovered matches are flagged with `is_new = 1` until acknowledged.
4. **Domain Rule Provenance**: Matches auto-classified by a domain rule store `auto_classified_by_rule_id`. A manual classification override by the user clears this rule reference and is permanently respected on subsequent scans.
5. **Path Traversal Protection**: Photo streaming endpoints strictly verify that the requested file resolves within an active, enabled library root using `os.path.commonpath`.

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
- Remote candidate match images are loaded directly in the user's browser with `referrerpolicy="no-referrer"` and safe fallbacks.
- The server binds strictly to `127.0.0.1`.

---

## 9. UX & Design Principles

- **Professional Photography Aesthetic**: Elegant dark/neutral theme (`carbon-950` to `carbon-800`), restrained typography, generous spacing, image-first presentation.
- **Efficient Match Review**: Discoveries are presented with side-by-side original and found thumbnails, quick classification buttons, direct link to live web pages, inline notes, and a high-resolution inspection modal.
- **Intentional States**: Explicit empty states, loading skeletons, progress modals, and error boundaries for all views.

---

## 10. Testing & Verification

- **Backend Tests**: Run `pytest tests/backend` to verify indexing, database migrations, rescan idempotency, domain rules, cost estimations, and full API workflows.
- **Frontend Build**: Run `npm run build` in `frontend/` to generate `frontend/dist`.
- **System Launch**: Execute `python start.py` or double-click `START_PHOTO_PRIVATEER.bat` to launch and test in a real browser.
