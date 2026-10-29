# Photo Privateer

> **Local Reverse Image Search Discovery for Photographers**

Photo Privateer is a self-contained, desktop-oriented local web application designed for professional photographers who want to periodically monitor the public web for unauthorized reuse of their photographs without relying on recurring SaaS subscription fees, remote databases, or cloud accounts.

---

## Table of Contents

1. [Product Overview](#product-overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [First-Time Setup](#first-time-setup)
5. [Launching Photo Privateer](#launching-photo-privateer)
6. [Development Mode](#development-mode)
7. [Deterministic Mock / Demo Mode](#deterministic-mock--demo-mode)
8. [Connecting Google Cloud Vision](#connecting-google-cloud-vision)
9. [Credential Handling & Privacy](#credential-handling--privacy)
10. [Local API Usage & Cost Estimation](#local-api-usage--cost-estimation)
11. [Data Storage & Backup](#data-storage--backup)
12. [Running Automated Tests](#running-automated-tests)
13. [Explicit Non-Goals](#explicit-non-goals)
14. [Troubleshooting](#troubleshooting)

---

## 1. Product Overview

Photo Privateer indexes your local photograph folders without moving, renaming, or modifying any of your original files. You select any number of photographs, click **Scan**, and Photo Privateer queries reverse-image-search providers (Google Cloud Vision Web Detection or offline Mock Provider).

Key Features:
- **Zero modification of source files**: Photos are read strictly in read-only binary mode.
- **Non-destructive library archiving**: Archive unmonitored libraries while preserving all historical photos and match triage records.
- **Historical permanence**: Rescanning updates timestamps and flags new discoveries without overwriting prior human classifications or notes.
- **Review Queue**: Classify matches as `UNREVIEWED`, `APPROVED`, `UNAUTHORIZED` (Infringing), or `IRRELEVANT` with an unobtrusive reset workflow.
- **Side-by-Side Detail Inspection**: Inspect the original photo and discovered web match side-by-side at high resolution without losing your place in the review queue.
- **Domain Rules**: Automatically whitelist portfolio sites or blacklist scrapers across subdomains.
- **Transparent Local Accounting**: Local tracker counts Google Vision units, projects pending scan costs, and enforces a conservative free-tier safety guard.
- **Asynchronous Cooperative Scanning**: Background thread execution with live polling, instant cooperative cancellation, and automatic recovery of interrupted sessions on startup.
- **Zero-Cost Google Auth Validation**: Test credentials and Application Default Credentials (ADC) token generation without consuming Cloud Vision quota (validates OAuth2 token refresh at $0.00 cost; does not assert Vision API enablement or billing status).
- **Perceptual Source Grouping & Deduplication**: Lightweight 64-bit dHash fingerprinting detects visually identical/near-identical candidate representations (crops, resized versions, re-exports) and lets you group them. Grouped representations share a single search call per scan, drastically cutting Google Vision quota while retaining distinct local photo files. Every member of a group shows the group's discoveries, and the scan confirmation tells you how many selected photos are covered by their group's primary representation. Re-exporting an edited photo over the same file keeps it in its group.
- **Privacy-First Remote Previews**: Candidate match images require user opt-in to fetch and are loaded with `referrerpolicy="no-referrer"`.
- **No Background Daemons**: Scanning occurs solely when explicitly requested by you.

---

## 2. Architecture

```text
React 19 + TypeScript 7 + Vite 8 + Tailwind CSS v4 UI
               ↓ REST / JSON
Local FastAPI Application (http://127.0.0.1:8765)
               ↓
Photo Privateer Core Engine
   ├── LibraryIndexer       (Read-only directory scanner, SHA-256)
   ├── ThumbnailCache       (Cached WebP thumbnails in ~/.photo_privateer/thumbnails)
   ├── ImageService         (Path traversal protection & containment check)
   ├── DomainRulesEngine    (Domain extraction and auto-classification)
   ├── UsageTracker         (Monthly usage aggregator & cost projection)
   ├── MigrationRunner      (Versioned idempotent schema migrations)
   └── ScanEngine           (Asynchronous batch dispatch, cancellation, persistence)
               ↓
Persistence & Search Providers
   ├── SQLite Database      (~/.photo_privateer/photo_privateer.sqlite with WAL mode)
   ├── MockSearchProvider   (Deterministic offline edge cases)
   └── GoogleVisionProvider (Official google-cloud-vision client & ADC support)
```

The application is served as a single local process: FastAPI binds strictly to `127.0.0.1` and serves both the REST API and the compiled React SPA from `frontend/dist`.

---

## 3. Prerequisites

- **Operating System**: Windows 10/11 (or macOS / Linux).
- **Python**: Version 3.14 (canonical supported runtime; Python 3.11+ supported on a compatibility fallback basis).
- **Node.js**: Version 24 LTS (only needed for first-time frontend build, test execution, or frontend development; not needed during normal launch after the frontend is compiled).

---

## 4. First-Time Setup

Run the PowerShell bootstrap script in the repository root:

```powershell
.\setup.ps1
```

Or execute manually:

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install Python dependencies
pip install -r requirements-dev.txt

# 3. Build production frontend (Node 24 LTS)
cd frontend
npm ci
npm run build
cd ..

# 4. Initialize SQLite schema
python -c "from backend.database import init_db; init_db()"
```


---

## 5. Launching Photo Privateer

### Method 1: Double-Click Launcher (Windows)
Double-click `START_PHOTO_PRIVATEER.bat` in File Explorer.

### Method 2: Python Command
From the repository root:
```powershell
python start.py
```

This will:
1. Verify the Python environment and build distribution.
2. Start the local FastAPI server at `http://127.0.0.1:8765`.
3. Automatically open Photo Privateer in your default web browser.

---

## 6. Development Mode

To modify the frontend with instant Vite Hot Module Replacement (HMR):

1. Start the backend API:
   ```powershell
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
   ```

2. Start the Vite dev server in a separate terminal:
   ```powershell
   cd frontend
   npm run dev
   ```
   Open `http://localhost:5173`. Vite proxies all `/api/*` requests to port `8765`.

---

## 7. Deterministic Mock / Demo Mode

Photo Privateer ships with a deterministic **Mock Provider** enabled by default. This allows you to explore the entire UI, test workflows, index local photos, and run scans completely offline without a Google Cloud account.

Mock behaviors are deterministic based on image hashes and filenames:
- **Clean/Empty**: Images containing `clean` or `empty` in the filename produce 0 matches.
- **Multiple URLs**: Images containing `multi` simulate multiple match URLs on a single domain (`curated-exhibits.art`).
- **Simulated Provider Failure**: Images containing `fail` or `error` simulate an upstream API error, demonstrating that a single image failure does not abort the batch.
- **Standard Discovery**: Produces a legitimate client publication, a partial crop on a design blog, and an unauthorized wallpaper scraper.

The UI displays an amber **Mock Mode (Offline)** badge in the header whenever mock mode is selected.

---

## 8. Connecting Google Cloud Vision

To perform real reverse image searches on the live web:

### Primary Method: Application Default Credentials (ADC) — Recommended for Local Use
For local personal desktop use, Google Cloud's official and recommended client-library authentication is Application Default Credentials (ADC):
1. Install the [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install).
2. Initialize and configure your Google Cloud project:
   ```bash
   gcloud init
   ```
3. Acquire local user Application Default Credentials:
   ```bash
   gcloud auth application-default login
   ```
4. Set your active project as the quota project for client libraries:
   ```bash
   gcloud auth application-default set-quota-project YOUR_PROJECT_ID
   ```
5. Ensure the **Cloud Vision API** is enabled in your project ([GCP Console](https://console.cloud.google.com/apis/library/vision.googleapis.com) or `gcloud services enable vision.googleapis.com`).

Photo Privateer automatically detects local ADC credentials on Windows (`%APPDATA%\gcloud\application_default_credentials.json`) and Linux/macOS (`~/.config/gcloud/application_default_credentials.json`). No file path configuration is necessary in Settings—leave the credentials path empty and click **Test Authentication**.
*(Note: The "Test Authentication" button validates OAuth2 credential token refresh at $0.00 cost; it verifies your credentials can authenticate with Google's token endpoint, but does not assert that the Cloud Vision API is enabled or billed in your GCP project).*

### Alternative Method: Service Account JSON Key
If you prefer to isolate access with a dedicated Service Account:
1. In the [Google Cloud Console](https://console.cloud.google.com/), navigate to **IAM & Admin > Service Accounts** and create a service account (e.g. `photo-privateer-runner`).
2. Grant the service account the **Service Usage Consumer** role (`roles/serviceusage.serviceUsageConsumer`) in your project.
   *(Note: Photo Privateer uploads raw image bytes directly to Google Cloud Vision Web Detection; no Google Cloud Storage buckets or `roles/storage.objectViewer` permissions are required).*
3. Under the created service account, go to **Keys > Add Key > Create new key > JSON**.
4. Save the downloaded `.json` file to a private, non-public directory on your machine (e.g. `C:\Users\YourUser\.secrets\gcp-vision-key.json`).
5. In Photo Privateer's **Settings** tab:
   - Select **Google Cloud Vision** as the active provider.
   - Enter the absolute path to your downloaded `.json` file.
   - Click **Save Settings** and **Test Authentication**.


---

## 9. Credential Handling & Privacy

- **Never Committed**: `.gitignore` strictly ignores `*credential*.json`, `*secret*.json`, `.env`, and private key formats.
- **Backend-Owned**: Google credentials are read exclusively by the local Python process. The frontend JavaScript client never receives private keys.
- **Local HTTP boundary**: Every route (API, original photographs, thumbnails, static assets and SPA) requires one valid `Host`: `localhost`, an IPv4 address in `127.0.0.0/8`, or bracketed IPv6 loopback (`[::1]`), optionally followed by a port from 1 to 65535. Arbitrary domains, malformed/missing/duplicate Host headers and forwarded-host bypasses are rejected before routing or file access. Mutation requests additionally retain Origin/Referer and cross-site checks. Development uses `http://localhost:5173` or `http://127.0.0.1:5173`; the application uses port 8765 by default. CORS allows these documented origins; it does not replace Host validation.
- **No Path Traversal**: Photos and thumbnails are served through controlled application endpoints that verify file paths reside within registered library folders.
- **SSRF Mitigation**: Remote candidate preview thumbnails are rendered directly by the browser using `referrerpolicy="no-referrer"` with graceful fallback states.

---

## 10. Local API Usage & Cost Estimation

Google Cloud Vision pricing for **Web Detection** (as published in official GCP pricing documentation, August 2026):
- **First 1,000 units per calendar month**: **Free ($0.00)**.
- **Units beyond 1,000**: **$3.50 per 1,000 units** ($0.0035 per image).

Photo Privateer tracks every executed API call in SQLite and provides an **API Usage & Cost** dashboard:
- **Free-Tier Safety Guard**: Enabled by default. Scans that would exceed your configured free monthly allowance (1,000 units) are blocked unless you check an explicit authorization box.
- **Local Estimate Disclaimer**: Displayed prominently across the application. Local tracking may differ from official Google billing statements due to project-wide activity, currency conversion, taxes, or promotional credits.

---

## 11. Data Storage & Backup

All application state is stored locally in SQLite:
- **Database file**: `~/.photo_privateer/photo_privateer.sqlite` (or overridden by the `PHOTO_PRIVATEER_DATA_DIR` environment variable).
- **Cached thumbnails**: `~/.photo_privateer/thumbnails/*.webp`.

### How to Back Up Your History:

Create a verified local bundle using the maintenance command from the repository root:

```powershell
python -m backend.maintenance backup --profile "$HOME\.photo_privateer" --output "D:\PhotoPrivateerBackups\catalog-backup"
python -m backend.maintenance verify "D:\PhotoPrivateerBackups\catalog-backup"
```

Choose an output directory that does not exist. The bundle includes committed SQLite/WAL history and registered managed artifacts, with hashes and a versioned manifest. Originals, preview caches and credentials are excluded; back up your source photos separately. Prefer an idle catalog, since writes wait during backup. Restore into a fresh profile to preserve your previous catalog. See [Backup and recovery](docs/BACKUP_RECOVERY.md) for restoration, library relinking and pre-migration recovery instructions.

---

## 12. Running Automated Tests

Photo Privateer includes a comprehensive, multi-tiered test suite ensuring full offline reproducibility and zero regressions.

### Tier 1: Backend Integration & Resilience Suite
Runs the complete Python pytest suite covering schema migrations, non-destructive archiving, cooperative cancellation, startup crash recovery, SHA-256 rename reconciliation, disk presence restoration, and zero-cost Google auth validation:
```powershell
pytest -v tests/backend
```

### Tier 2: Frontend Unit & Component Tests
Runs Vitest unit tests verifying components including the privacy opt-in thumbnail loader, live scan progress modal with cooperative cancellation, and confirmation dialogs:
```powershell
cd frontend
npm test
```

### Tier 3: Production Frontend Build
Validates TypeScript type safety, asset bundling, and compiles production assets into `frontend/dist/`:
```powershell
cd frontend
npm run build
```

### Tier 4: Playwright End-to-End Browser Tests
Launches an automated headless browser test against a live backend instance verifying real user journeys across 8 scenarios (library indexing, mock scanning with live polling, review queue triage with privacy opt-in, ADC auth testing and library archiving, cooperative scan cancellation, project batch assignment with filtering, perceptual grouping candidate review and representation consolidation, and permanent library purge with source photo preservation):
```powershell
cd frontend
npm run test:e2e
```

---

## 13. Explicit Non-Goals

- **No Continuous Background Daemons**: Photo Privateer will never run scheduled crawlers, hourly crons, or background watchers without your explicit instruction.
- **No Remote Application Server**: All computation, indexing, and storage happens on `127.0.0.1`.
- **No Accounts or Telemetry**: No tracking, phone-home metrics, or SaaS accounts.

---

## 14. Troubleshooting

| Issue | Resolution |
| :--- | :--- |
| **Port 8765 already in use** | Set `PHOTO_PRIVATEER_PORT=8766` in your environment or launch command: `$env:PHOTO_PRIVATEER_PORT=8766; python start.py`. |
| **Thumbnail generation fails** | Ensure your image is a supported format (JPEG, PNG, WebP, TIFF). Pillow transposes EXIF orientation automatically. |
| **Google Vision returns `PermissionDenied`** | Verify that the Cloud Vision API is enabled in your GCP project (`gcloud services enable vision.googleapis.com`) and that ADC has a valid quota project set (`gcloud auth application-default set-quota-project PROJECT_ID`) or the service account has the **Service Usage Consumer** role. |

| **Frontend displays white screen** | Run `npm run build` inside `frontend/` to ensure `frontend/dist/index.html` exists. |
