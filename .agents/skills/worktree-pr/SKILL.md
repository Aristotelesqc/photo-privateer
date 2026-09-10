---
name: worktree-pr
description: Standardized workflow for developing, testing, verifying, and publishing changes via isolated Git worktrees and GitHub Pull Requests
---

# worktree-pr

This skill defines and standardizes the mandatory development and publication workflow for Photo Privateer using isolated Git worktrees and GitHub Pull Requests.

---

## 1. Core Principles & Invariants

1. **Zero Direct-to-Main Mutations**:
   - `main` is strictly protected.
   - Never commit directly to `main`.
   - Never push directly to `main`.
   - Never merge Pull Requests automatically; they must remain open for independent human and CI review.

2. **Isolated Worktree Development**:
   - All feature development, bug fixes, refactoring, dependency upgrades, and audit corrections must occur in an isolated Git worktree on a dedicated feature branch.
   - The primary repository working directory (e.g. `c:\GitHub\photo-privateer`) remains clean on `main` at all times.

3. **Multi-Tier Verification Before Publishing**:
   - All verification tiers (Tier 1 pytest, Tier 2 Vitest, Tier 3 Vite build, Tier 4 Playwright E2E) must pass inside the worktree before committing or pushing.

---

## 2. Standard Workflow

### Step 1: Inspect Baseline & Create Worktree

From the primary repository, inspect the baseline `origin/main` commit and create a sibling worktree on a dedicated branch:

```powershell
# Inspect baseline commit
git rev-parse HEAD
git rev-parse origin/main

# Create sibling worktree under ../photo-privateer-worktrees/<branch-name>
git worktree add ../photo-privateer-worktrees/<branch-name> -b <branch-name> origin/main
```

### Step 2: Initialize Worktree Environment

Navigate to the worktree and ensure dependencies are installed:

```powershell
Set-Location ../photo-privateer-worktrees/<branch-name>

# Ensure frontend dependencies are installed
Push-Location frontend
npm ci
Pop-Location
```

### Step 3: Implement & Test

Make all changes inside the isolated worktree directory. Execute the 4-tier verification suite:

```powershell
# Tier 1: Backend tests
python -m pytest -v tests/backend

# Tier 2: Frontend unit tests
Push-Location frontend
npm test
Pop-Location

# Tier 3: Frontend production build
Push-Location frontend
npm run build
Pop-Location

# Tier 4: Playwright E2E tests
Push-Location frontend
npm run test:e2e
Pop-Location
```

### Step 4: Verify Git Identity & Commit

Ensure git identity aligns with the repository owner:

```powershell
git config user.name
git config user.email

# Stage changes and commit atomically
git status
git add .
git commit -m "<type>(<scope>): <clear description of changes>"
```

### Step 5: Push Branch & Open Pull Request

Push the feature branch to origin and create the Pull Request using GitHub CLI:

```powershell
# Push feature branch
git push -u origin <branch-name>

# Create Pull Request targeting main (remains OPEN)
gh pr create --base main --head <branch-name> --title "<type>: <title>" --body "<summary and verification evidence>"
```

### Step 6: Cleanup (Post-Review & Post-Merge)

Once the PR has been reviewed and merged on GitHub:

```powershell
# Return to primary repository
Set-Location ../photo-privateer
git checkout main
git pull origin main

# Remove the worktree
git worktree remove ../photo-privateer-worktrees/<branch-name>

# Delete the local feature branch
git branch -d <branch-name>
```
