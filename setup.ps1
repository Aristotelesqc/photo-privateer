# Photo Privateer First-Run Setup Script for Windows PowerShell
$ErrorActionPreference = "Stop"

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Photo Privateer First-Time Setup and Bootstrap" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# 1. Verify Python
Write-Host "[1/4] Checking Python environment..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python was not found. Please install Python 3.9 or higher and add it to PATH."
}
Write-Host "  Found: $pythonVersion" -ForegroundColor Green

# 2. Install Python dependencies
Write-Host "[2/4] Installing Python backend dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python dependencies via pip."
}
Write-Host "  Backend dependencies installed successfully." -ForegroundColor Green

# 3. Build frontend
Write-Host "[3/4] Installing frontend dependencies and building distribution..." -ForegroundColor Yellow
Push-Location frontend
try {
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed running 'npm install' in frontend directory."
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed running 'npm run build' in frontend directory."
    }
    Write-Host "  Frontend compiled successfully to frontend/dist." -ForegroundColor Green
} finally {
    Pop-Location
}

# 4. Initialize database
Write-Host "[4/4] Initializing local SQLite schema..." -ForegroundColor Yellow
python -c "from backend.database import init_db; init_db(); print('SQLite schema ready.')"

Write-Host "===================================================" -ForegroundColor Green
Write-Host "  Photo Privateer Setup Complete!" -ForegroundColor Green
Write-Host "  You can now start Photo Privateer anytime by:" -ForegroundColor White
Write-Host "  1. Double-clicking START_PHOTO_PRIVATEER.bat, OR" -ForegroundColor White
Write-Host "  2. Running: python start.py" -ForegroundColor White
Write-Host "===================================================" -ForegroundColor Green
