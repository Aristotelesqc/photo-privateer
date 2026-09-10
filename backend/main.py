"""Photo Privateer FastAPI application entry point."""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import FRONTEND_DIST_DIR, HOST, PORT
from backend.database import init_db
from backend.api import (
    libraries,
    photos,
    scans,
    matches,
    rules,
    usage,
    settings,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("photo_privateer")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Photo Privateer SQLite database...")
    init_db()
    logger.info("Database initialized successfully.")
    
    # Startup crash recovery: mark dangling RUNNING sessions as INTERRUPTED
    try:
        from backend.database import get_connection
        from backend.repositories.usage_repo import UsageRepository
        with get_connection() as conn:
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
    version="1.0.0",
    lifespan=lifespan,
)

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
