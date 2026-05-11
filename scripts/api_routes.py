"""
api_routes.py — GradeOps FastAPI Route Stubs
Drop-in route definitions that expose the pipeline to your frontend.

Mount in your main FastAPI app:
    from api_routes import router
    app.include_router(router, prefix="/api/v1")

Environment variables needed:
    GRADEOPS_OCR_BACKEND   = qwen_vl | nougat | mock
    GRADEOPS_LLM_PROVIDER  = openai | anthropic | mock
    GRADEOPS_LLM_MODEL     = gpt-4o
    GRADEOPS_STORAGE       = local | s3
    GRADEOPS_DATA_DIR      = ./gradeops_data   (for local storage)
    OPENAI_API_KEY         = sk-...            (if using OpenAI)
"""

import os
import uuid
import logging
import tempfile
from typing import Annotated

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from models import (
    ExamBatch, Rubric, RubricCriterion,
    TAReviewPayload, GradeStatus, UserRole
)
from pipeline import GradeOpsPipeline, PipelineConfig

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────
# Shared pipeline instance (singleton)
# ─────────────────────────────────────────────

_pipeline: GradeOpsPipeline | None = None

def get_pipeline() -> GradeOpsPipeline:
    global _pipeline
    if _pipeline is None:
        cfg = PipelineConfig(
            ocr_backend   = os.getenv("GRADEOPS_OCR_BACKEND", "mock"),
            llm_provider  = os.getenv("GRADEOPS_LLM_PROVIDER", "mock"),
            llm_model     = os.getenv("GRADEOPS_LLM_MODEL", "gpt-4o"),
            storage_backend = os.getenv("GRADEOPS_STORAGE", "local"),
            storage_kwargs  = {"base_dir": os.getenv("GRADEOPS_DATA_DIR", "./gradeops_data")},
        )
        _pipeline = GradeOpsPipeline(cfg)
    return _pipeline


# ─────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────

class RubricCriterionIn(BaseModel):
    criterion_id:      str
    description:       str
    max_points:        float
    required_keywords: list[str] = []
    partial_credit:    bool = True

class RubricIn(BaseModel):
    question_number: int
    total_points:    float
    criteria:        list[RubricCriterionIn]
    strict_mode:     bool = False

class ExamSubmitRequest(BaseModel):
    course_id:     str
    instructor_id: str
    rubrics:       list[RubricIn]


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

# ── POST /exams  ──────────────────────────────
@router.post("/exams", summary="Submit exam PDFs + rubric for grading")
async def submit_exam(
    course_id:     Annotated[str, Form()],
    instructor_id: Annotated[str, Form()],
    rubrics_json:  Annotated[str, Form()],         # JSON-encoded list[RubricIn]
    pdfs:          list[UploadFile] = File(...),
    pipeline:      GradeOpsPipeline = Depends(get_pipeline),
):
    """
    Accepts multipart form with:
      - course_id, instructor_id
      - rubrics_json: JSON string of rubric definitions
      - pdfs: one PDF file per student (filename = student_id.pdf)

    Returns exam_id and summary stats.
    """
    import json as _json

    exam_id = str(uuid.uuid4())

    # Save uploaded PDFs to temp dir
    tmp_dir = tempfile.mkdtemp()
    pdf_paths: list[str] = []
    for upload in pdfs:
        dest = os.path.join(tmp_dir, upload.filename)
        with open(dest, "wb") as f:
            f.write(await upload.read())
        pdf_paths.append(dest)

    # Parse rubrics
    raw_rubrics = _json.loads(rubrics_json)
    rubrics = [
        Rubric(
            rubric_id=str(uuid.uuid4()),
            exam_id=exam_id,
            **r,
            criteria=[RubricCriterion(**c) for c in r.pop("criteria", [])],
        )
        for r in raw_rubrics
    ]

    batch = ExamBatch(
        exam_id=exam_id,
        course_id=course_id,
        instructor_id=instructor_id,
        pdf_paths=pdf_paths,
        rubrics=rubrics,
        student_count=len(pdf_paths),
    )

    try:
        report = pipeline.run_exam(batch)
        return {"exam_id": exam_id, "summary": report.summary()}
    except Exception as exc:
        logger.exception("Pipeline error for exam %s", exam_id)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /exams/{exam_id}/dashboard  ───────────
@router.get("/exams/{exam_id}/dashboard", summary="TA review dashboard data")
async def get_dashboard(
    exam_id:  str,
    pipeline: GradeOpsPipeline = Depends(get_pipeline),
):
    """
    Returns pending AI grades (with crop paths) for TA review.
    """
    try:
        data = pipeline.get_dashboard_data(exam_id)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /exams/{exam_id}/grades  ──────────────
@router.get("/exams/{exam_id}/grades", summary="All grades for an exam")
async def get_grades(
    exam_id:         str,
    student_id:      str | None = None,
    question_number: int | None = None,
    pipeline:        GradeOpsPipeline = Depends(get_pipeline),
):
    grades = pipeline.storage.load_grades(exam_id, student_id, question_number)
    return [g.model_dump() for g in grades]


# ── POST /grades/review  ──────────────────────
@router.post("/grades/review", summary="TA approves or overrides a grade")
async def ta_review(
    payload:  TAReviewPayload,
    pipeline: GradeOpsPipeline = Depends(get_pipeline),
):
    """
    Payload:
        grade_id:       str
        ta_id:          str
        action:         "approve" | "override"
        override_score: float  (required if action == "override")
        override_note:  str    (optional)
    """
    if payload.action not in ("approve", "override"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'override'")
    pipeline.apply_ta_review(payload)
    return {"status": "ok", "grade_id": payload.grade_id, "action": payload.action}


# ── GET /exams/{exam_id}/plagiarism  ──────────
@router.get("/exams/{exam_id}/plagiarism", summary="Plagiarism flags for an exam")
async def get_plagiarism_flags(
    exam_id:   str,
    min_score: float = 0.0,
    pipeline:  GradeOpsPipeline = Depends(get_pipeline),
):
    """Returns all grades with plagiarism_flag=True."""
    grades = pipeline.storage.load_grades(exam_id)
    flagged = [
        g.model_dump()
        for g in grades
        if g.plagiarism_flag and g.plagiarism_similarity >= min_score
    ]
    return {"exam_id": exam_id, "flagged_count": len(flagged), "results": flagged}


# ── GET /health  ──────────────────────────────
@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "service": "GradeOps"}
