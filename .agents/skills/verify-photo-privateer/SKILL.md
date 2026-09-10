---
name: verify-photo-privateer
description: Repeatable quality and verification audit for Photo Privateer application
---

# verify-photo-privateer

This skill runs an end-to-end verification audit of the Photo Privateer application across backend tests, frontend builds, database integrity, and production launcher checks.

## Verification Workflow

### 1. Backend Automated Tests
Run pytest across all unit, integration, and resilience tests:
```powershell
pytest -v tests/backend
```
Ensure all 19 tests pass (indexing, hashing immutability, versioned SQLite migrations, rescan history preservation, domain rules, cost estimation, cooperative scan cancellation, crash recovery, rename reconciliation, and zero-cost authentication).

### 2. Frontend Unit Tests (Vitest)
Run Vitest component unit tests:
```powershell
Push-Location frontend
npm test
Pop-Location
```
Ensure all 10 unit tests pass (Thumbnail privacy opt-in, ScanProgressModal polling, ScanConfirmModal usable photo breakdown).

### 3. Frontend Production Build
Run TypeScript checking and Vite production bundling:
```powershell
Push-Location frontend
npm run build
Pop-Location
```
Verify `frontend/dist/index.html` and bundled assets compile cleanly with zero TypeScript errors.

### 4. End-to-End Browser Tests (Playwright)
Run the automated Playwright browser test suite covering all 5 core user journeys:
```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```
Scenarios verified:
- Scenario 1: App navigation and Library folder management.
- Scenario 2: Reverse image scan execution with live progress polling.
- Scenario 3: Review Queue triage, privacy opt-in, and inspection modal.
- Scenario 4: Settings authentication status and non-destructive library archive.
- Scenario 5: Cooperative scan cancellation workflow.

### 5. Launcher & Port Integrity Check
Verify that `start.py` can bind cleanly to localhost `127.0.0.1:8765`:
```powershell
python -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 8765)); s.close(); print('Port 8765 is available.')"
```

### 6. Mock Mode Safety Guarantee
Confirm no real Google Cloud API calls can occur during testing or when Mock Provider is active:
```powershell
pytest -k "test_mock_provider_scenarios" tests/backend
```
