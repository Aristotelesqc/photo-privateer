---
name: bump-version
description: Update Photo Privateer application version, rebuild assets, run verification tests, and publish release commits
---

# bump-version

This skill orchestrates the end-to-end version release process for Photo Privateer across backend and frontend codebases, rebuilds production assets, executes full verification tests, and pushes aligned release commits.

## Canonical Version Locations

The application version is synchronized across four files:
- `backend/config.py` (`APP_VERSION`)
- `frontend/src/version.ts` (`APP_VERSION`)
- `frontend/package.json` (`version`)
- `frontend/package-lock.json` (`version`)

The frontend header imports and displays `v{APP_VERSION}` dynamically.

## Script Path Resolution Convention

When writing or modifying helper scripts nested within `.agents/skills/<name>/scripts/`, note that the repository workspace root is exactly 5 directory levels above the script (`Path(__file__).resolve().parents[4]`). Always test and dogfood script execution from the repository root to verify cross-directory path resolution.

## Version Update Workflow

### 1. Bump the Version
Run the automated version bumper script from the repository root:

```powershell
# Bump patch version (e.g. 1.0.0 -> 1.0.1):
python .agents/skills/bump-version/scripts/bump_version.py --patch

# Or bump minor version (e.g. 1.0.0 -> 1.1.0):
python .agents/skills/bump-version/scripts/bump_version.py --minor

# Or bump major version (e.g. 1.0.0 -> 2.0.0):
python .agents/skills/bump-version/scripts/bump_version.py --major

# Or specify an explicit semantic version:
python .agents/skills/bump-version/scripts/bump_version.py 1.0.1
```

### 2. Rebuild Frontend Production Distribution
Recompile TypeScript and the Vite production bundle to ensure `frontend/dist/` contains the updated version:
```powershell
Push-Location frontend
npm run build
Pop-Location
```

### 3. Execute Verification Suites
Run backend and frontend tests to ensure zero regressions with the new version:
```powershell
# Tier 1: Backend tests
pytest -v tests/backend

# Tier 2: Frontend unit tests
Push-Location frontend
npm test
Pop-Location

# Tier 4: Playwright E2E browser tests
Push-Location frontend
npm run test:e2e
Pop-Location
```

### 4. Git Identity Alignment & Commit
Ensure git author matches the repository owner before committing (AGENTS.md Invariant §11):
```powershell
git config user.name
git config user.email
```

Stage and create an atomic release commit:
```powershell
git add .
git commit -m "chore(release): bump version to v<new_version>"
```

### 5. Push to Remote
Push the release commit to the upstream branch:
```powershell
git push origin main
```
