---
name: verify-photo-privateer
description: Repeatable quality and verification audit for Photo Privateer application
---

# verify-photo-privateer

This skill runs an end-to-end verification audit of the Photo Privateer application across backend tests, frontend builds, database integrity, and production launcher checks.

## Verification Workflow

### 1. Backend Automated Tests
Run pytest with full verbosity:
```powershell
pytest -v tests/backend
```
Ensure all 12 tests pass (indexing, hashing immutability, SQLite migrations, rescan history preservation, domain rules, cost estimation, and API workflows).

### 2. Frontend Production Build
Run TypeScript checking and Vite production bundling:
```powershell
Push-Location frontend
npm run build
Pop-Location
```
Verify `frontend/dist/index.html` and bundled assets exist without TypeScript compilation errors.

### 3. Launcher & Port Integrity Check
Verify that `start.py` can bind cleanly to localhost `127.0.0.1:8765`:
```powershell
python -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 8765)); s.close(); print('Port 8765 is available.')"
```

### 4. Database Schema Initialization
Test isolated SQLite schema bootstrap:
```powershell
python -c "from backend.database import init_db; init_db(); print('SQLite schema initialized.')"
```

### 5. Mock Mode Safety Guarantee
Confirm no real Google Cloud API calls can occur during testing or when Mock Provider is active:
```powershell
pytest -k "test_mock_provider_scenarios" tests/backend
```
