
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
#
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

from fastapi import FastAPI

# Import routers from the routes directory
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
        "service": "API Guardian Backend"
    }
