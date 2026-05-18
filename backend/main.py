"""
main.py — GradeOps FastAPI Application Entry Point

Run locally:
    uvicorn main:app --reload --port 8000

Run in production:
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from api_routes import router
from auth import auth_router
from database import init_db


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Lifespan (startup / shutdown)
# FIX #12: replaced deprecated @app.on_event with the lifespan context manager
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    logger.info("=" * 60)
    logger.info("GradeOps v%s starting up", settings.app_version)
    logger.info("OCR backend   : %s", settings.ocr_backend)
    logger.info("LLM provider  : %s (%s)", settings.llm_provider, settings.llm_model)
    logger.info("Storage       : %s", settings.storage_backend)
    logger.info("Debug mode    : %s", settings.debug)
    logger.info("=" * 60)

    # Initialise PostgreSQL — creates tables & seeds demo users
    await init_db()

    yield  # application runs here

    # ── shutdown ──
    logger.info("GradeOps shutting down.")


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Human-in-the-Loop (HITL) AI grading pipeline. "
        "Upload scanned exam PDFs, get AI-generated grades with justifications, "
        "then let TAs rapidly approve or override via the review dashboard."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,  # FIX #12
)


# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

app.include_router(auth_router, prefix="/api/v1")          # /api/v1/auth/...
app.include_router(router,      prefix="/api/v1")          # /api/v1/exams/...


# ─────────────────────────────────────────────
# Static files — serve cropped answer images
# FIX: mount /crops so browser can fetch crop URLs like /crops/exam_q1_abc.png
# ─────────────────────────────────────────────

CROPS_DIR = os.path.abspath("./crops")
os.makedirs(CROPS_DIR, exist_ok=True)
app.mount("/crops", StaticFiles(directory=CROPS_DIR), name="crops")


# ─────────────────────────────────────────────
# Root redirect
# ─────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs":    "/docs",
        "health":  "/api/v1/health",
    }


# ─────────────────────────────────────────────
# Dev runner
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
