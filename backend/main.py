"""Photo Privateer FastAPI application entry point."""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import ipaddress
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.config import FRONTEND_DIST_DIR, HOST, PORT, APP_VERSION
from backend.database import init_db
from backend.api import (
    libraries,
    photos,
    scans,
    matches,
    rules,
    usage,
    settings,
    groups,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("photo_privateer")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dynamic DB path resolution: allows test suites and isolated environments to inject target database
    from backend.database import get_db_path, get_connection, init_db
    target_db_path = getattr(app.state, "db_path", None) or get_db_path()

    logger.info(f"Initializing Photo Privateer SQLite database at: {target_db_path}")
    init_db(target_db_path)
    logger.info("Database initialized successfully.")
    
    # Startup crash recovery: mark dangling RUNNING sessions as INTERRUPTED
    try:
        from backend.repositories.usage_repo import UsageRepository
        with get_connection(target_db_path) as conn:
            repo = UsageRepository(conn)
            recovered = repo.recover_interrupted_sessions()
            if recovered > 0:
                logger.warning(f"Recovered {recovered} dangling scan session(s) marked as INTERRUPTED.")
    except Exception as e:
        logger.error(f"Failed to recover interrupted scan sessions: {e}")

    yield
    logger.info("Photo Privateer shutting down.")

app = FastAPI(
    title="Photo Privateer",
    description="Local reverse-image-search discovery and monitoring tool for photographers.",
    version=APP_VERSION,
    lifespan=lifespan,
)

def create_app(db_path: Path | str | None = None) -> FastAPI:
    """Helper app factory to configure an isolated database path on app state."""
    if db_path is not None:
        from backend.database import set_db_path
        p = Path(db_path).resolve()
        app.state.db_path = p
        set_db_path(p)
    return app

def is_allowed_origin(origin_str: str) -> bool:
    """Validate that an origin or referer URL belongs strictly to a local loopback interface."""
    if not origin_str:
        return False
    if origin_str == "http://testserver":
        return True
    try:
        parsed = urlparse(origin_str)
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() == "localhost":
            return True
        ip = ipaddress.ip_address(hostname)
        return ip.is_loopback
    except Exception:
        return False

@app.middleware("http")
async def enforce_local_origin_protection(request: Request, call_next):
    """Enforces origin validation and blocks cross-site CSRF requests for state-changing API endpoints."""
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        sec_fetch_site = request.headers.get("sec-fetch-site")
        if sec_fetch_site == "cross-site":
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site requests to Photo Privateer API are forbidden."},
            )
        origin = request.headers.get("origin")
        if origin:
            if not is_allowed_origin(origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Forbidden origin: '{origin}'. Only local loopback origins are permitted."},
                )
        else:
            referer = request.headers.get("referer")
            if referer and not is_allowed_origin(referer):
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Forbidden referer: '{referer}'. Only local loopback origins are permitted."},
                )
    return await call_next(request)

# CORS: Restricted strictly to localhost origins for local security
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(libraries.router)
app.include_router(photos.router)
app.include_router(scans.router)
app.include_router(matches.router)
app.include_router(rules.router)
app.include_router(usage.router)
app.include_router(settings.router)
app.include_router(groups.router)

# Serve compiled frontend if available
if FRONTEND_DIST_DIR.is_dir():
    # Mount assets
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # Serve index.html for root and SPA routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Don't intercept API routes
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        dist_root = FRONTEND_DIST_DIR.resolve()
        candidate = (dist_root / full_path).resolve()

        # Prevent path traversal outside frontend/dist
        if candidate.is_file():
            try:
                if os.path.commonpath([str(dist_root), str(candidate)]) == str(dist_root):
                    return FileResponse(str(candidate))
            except ValueError:
                pass

        index_file = dist_root / "index.html"
        if index_file.is_file():
            return FileResponse(str(index_file))
        return {"app": "Photo Privateer API", "status": "running"}
else:
    @app.get("/")
    async def root():
        return {
            "app": "Photo Privateer API",
            "status": "running",
            "notice": "Frontend distribution not yet built. Run 'npm run build' inside /frontend.",
        }

def start_server():
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)

if __name__ == "__main__":
    start_server()
