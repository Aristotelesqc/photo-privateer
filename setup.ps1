# Photo Privateer First-Run Setup Script for Windows PowerShell
$ErrorActionPreference = "Stop"

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Photo Privateer First-Time Setup and Bootstrap" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# 1. Verify Python (Python 3.11+ supported, Python 3.14 canonical)
Write-Host "[1/5] Checking Python environment..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python was not found. Please install Python 3.14 or higher and add it to PATH."
}
Write-Host "  Found: $pythonVersion" -ForegroundColor Green
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Photo Privateer requires Python 3.11 or higher (Python 3.14 canonical recommended). Found: $pythonVersion"
}
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [NOTE] Python 3.14 is the canonical target. Running in backwards-compatible mode with $pythonVersion." -ForegroundColor Yellow
}

# 2. Virtual Environment (.venv)
Write-Host "[2/5] Configuring virtual environment (.venv)..." -ForegroundColor Yellow
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
$venvPython = ".venv\Scripts\python.exe"
$venvPip = ".venv\Scripts\pip.exe"
Write-Host "  Virtual environment ready: .venv" -ForegroundColor Green

# 3. Install Python dependencies
Write-Host "[3/5] Installing Python backend & dev dependencies..." -ForegroundColor Yellow
& $venvPip install --upgrade pip
& $venvPip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python dependencies via pip."
}
Write-Host "  Backend dependencies installed successfully." -ForegroundColor Green

# 4. Check Node.js and build frontend
Write-Host "[4/5] Checking Node.js and building frontend distribution..." -ForegroundColor Yellow
$nodeVersion = node --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Node.js was not found. Please install Node.js 24 LTS."
}
node -e "const [major] = process.versions.node.split('.').map(Number); process.exit(major >= 24 ? 0 : 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Photo Privateer requires Node.js 24 LTS or higher for setup and build. Found: $nodeVersion"
}
Write-Host "  Found: $nodeVersion" -ForegroundColor Green

Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed running 'npm ci' in frontend directory."
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed running 'npm run build' in frontend directory."
    }
    Write-Host "  Frontend compiled successfully to frontend/dist." -ForegroundColor Green
} finally {
    Pop-Location
}

# 5. Initialize database
Write-Host "[5/5] Initializing local SQLite schema..." -ForegroundColor Yellow
& $venvPython -c "from backend.database import init_db; init_db(); print('SQLite schema ready.')"

Write-Host "===================================================" -ForegroundColor Green
Write-Host "  Photo Privateer Setup Complete!" -ForegroundColor Green
Write-Host "  You can now start Photo Privateer anytime by:" -ForegroundColor White
Write-Host "  1. Double-clicking START_PHOTO_PRIVATEER.bat, OR" -ForegroundColor White
Write-Host "  2. Running: python start.py" -ForegroundColor White
Write-Host "===================================================" -ForegroundColor Green

