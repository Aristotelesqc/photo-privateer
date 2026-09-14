"""Photo Privateer local application launcher."""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import webbrowser
import threading
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent

def check_environment():
    # 1. Verify Python version (canonical 3.14+, backwards compatibility fallback 3.11+)
    if sys.version_info < (3, 11):
        print(f"ERROR: Photo Privateer canonical supported runtime is Python 3.14 (Python 3.11+ compatibility fallback). Running: {sys.version}")
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

def is_port_available(host: str, port: int) -> bool:
    """Verify socket port is available before uvicorn bind."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False

def wait_for_server_and_open_browser(url: str, timeout: float = 15.0):
    """Polls the local server endpoint until it is accepting connections, then opens the browser."""
    def _poll_and_open():
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PhotoPrivateerBootstrap/1.0"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status in (200, 304):
                        print(f"Server is ready. Opening Photo Privateer in default browser: {url}")
                        webbrowser.open_new_tab(url)
                        return
            except Exception:
                time.sleep(0.2)
        print(f"Notice: Server startup took longer than {timeout}s. You can open manually at: {url}")

    t = threading.Thread(target=_poll_and_open, daemon=True, name="browser-opener")
    t.start()

def main():
    parser = argparse.ArgumentParser(description="Photo Privateer Desktop Server")
    parser.add_argument("--no-browser", action="store_true", help="Start server without launching a web browser")
    parser.add_argument("--port", type=int, default=None, help="Override HTTP port")
    parser.add_argument("--host", type=str, default=None, help="Override HTTP host binding")
    args = parser.parse_args()

    check_environment()

    # Import backend configuration
    sys.path.insert(0, str(WORKSPACE_ROOT))
    from backend.config import HOST, PORT, validate_loopback_host
    import uvicorn

    raw_host = args.host or HOST
    try:
        bind_host = validate_loopback_host(raw_host)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    bind_port = args.port or PORT
    if not is_port_available(bind_host, bind_port):
        print(f"ERROR: Port {bind_port} on {bind_host} is already in use.")
        print("Please stop any running Photo Privateer instance or specify an alternate port via --port.")
        sys.exit(1)

    url = f"http://{bind_host}:{bind_port}/"
    print("=" * 60)
    print("  Photo Privateer — Local Reverse Image Search Discovery")
    print("=" * 60)
    print(f"  * Binding strictly to: {bind_host}")
    print(f"  * Local Web URL:       {url}")
    print("  * Press Ctrl+C in this console to stop the server.")
    print("=" * 60)

    # Launch browser only once server is verified ready
    if not args.no_browser:
        wait_for_server_and_open_browser(url)
    else:
        print("  * Running in headless mode (--no-browser).")

    # Start FastAPI
    uvicorn.run(
        "backend.main:app",
        host=bind_host,
        port=bind_port,
        log_level="info",
        reload=False,
    )

if __name__ == "__main__":
    main()
