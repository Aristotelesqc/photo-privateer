"""Photo Privateer local application launcher."""
from __future__ import annotations

import os
import sys
import time
import webbrowser
import threading
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent

def check_environment():
    # 1. Verify Python version
    if sys.version_info < (3, 9):
        print("ERROR: Photo Privateer requires Python 3.9 or higher.")
        sys.exit(1)

    # 2. Verify backend dependencies
    missing = []
    for pkg in ["fastapi", "uvicorn", "pydantic", "PIL"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"ERROR: Missing required Python packages: {', '.join(missing)}")
        print("Please run: pip install -r requirements.txt")
        sys.exit(1)

    # 3. Verify frontend build
    dist_dir = WORKSPACE_ROOT / "frontend" / "dist"
    if not (dist_dir / "index.html").is_file():
        print("Frontend distribution not detected in frontend/dist.")
        print("Attempting automatic production build via npm...")
        frontend_dir = WORKSPACE_ROOT / "frontend"
        import subprocess
        try:
            subprocess.run(["npm", "run", "build"], cwd=str(frontend_dir), check=True)
            print("Frontend built successfully.")
        except Exception as e:
            print(f"Could not build frontend automatically: {e}")
            print("Please run 'npm install && npm run build' inside frontend/.")

def open_browser_delayed(url: str, delay_seconds: float = 1.2):
    def _open():
        time.sleep(delay_seconds)
        print(f"Opening Photo Privateer in default browser: {url}")
        webbrowser.open_new_tab(url)
    
    t = threading.Thread(target=_open, daemon=True)
    t.start()

def main():
    check_environment()

    # Import backend configuration
    sys.path.insert(0, str(WORKSPACE_ROOT))
    from backend.config import HOST, PORT
    import uvicorn

    url = f"http://{HOST}:{PORT}/"
    print("=" * 60)
    print("  Photo Privateer — Local Reverse Image Search Discovery")
    print("=" * 60)
    print(f"  * Binding strictly to: {HOST}")
    print(f"  * Local Web URL:       {url}")
    print("  * Press Ctrl+C in this console to stop the server.")
    print("=" * 60)

    # Launch browser automatically
    open_browser_delayed(url)

    # Start FastAPI
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )

if __name__ == "__main__":
    main()
