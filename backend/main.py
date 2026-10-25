
# ============================================================
# API Guardian - Main Application
# File: backend/main.py
#
# Purpose:
#   Entry point for the API Guardian FastAPI backend.
#
# Responsibilities:
#   - Initialize FastAPI
#   - Register GitHub and workspace routes
#   - Provide application health-check endpoints
# ============================================================

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from routes.migrations import router as migrations_router
from routes.repositories import router as repositories_router
from routes.workspaces import router as workspaces_router

# Initialize the FastAPI application
app = FastAPI(
    title="API Guardian",
    description="AI-Powered API Maintenance and Code Migration",
    version="0.1.0"
)


# Register repository metadata endpoints
app.include_router(repositories_router)

# Register repository workspace endpoints
app.include_router(workspaces_router)

app.include_router(migrations_router)


@app.get("/ui", include_in_schema=False)
def interactive_ui():
    """Serve the local interactive dashboard."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serve a favicon for browsers that request the conventional path."""
    return RedirectResponse("/favicon.svg")


@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg():
    """Serve the dashboard's vector favicon."""
    return FileResponse(
        Path(__file__).parent / "static" / "favicon.svg",
        media_type="image/svg+xml",
    )


@app.get("/")
def root():
    """
    Root endpoint for API Guardian.

    Returns basic information about the application.
    """

    return {
        "message": "Welcome to API Guardian!",
        "status": "running"
    }


@app.get("/health")
def health_check():
    """
    Check whether the backend service is running.

    Endpoint:
        GET /health
    """

    return {
        "status": "healthy",
        "service": "API Guardian Backend",
        "model": os.getenv("OLLAMA_MODEL", "gemma3:4b"),
    }
