"""
api_routes.py — GradeOps FastAPI Routes
Exposes the full pipeline over HTTP with RBAC enforcement.
"""

import json as _json
import logging
import shutil
import tempfile
import uuid
import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import csv
import io
from pydantic import BaseModel

from auth import require_instructor, require_ta_or_above
from database import UserORM
from background_tasks import task_manager, JobStatus
from config import settings
from models import (
    ExamBatch, GradeStatus, Rubric, RubricCriterion, TAReviewPayload
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
        storage_kwargs: dict = {}
        if settings.storage_backend == "local":
            storage_kwargs = {"base_dir": settings.storage_data_dir}
        elif settings.storage_backend == "s3":
            storage_kwargs = {
                "bucket":       settings.aws_s3_bucket,
                "dynamo_table": settings.aws_dynamo_table,
                "region":       settings.aws_region,
            }

        cfg = PipelineConfig(
            ocr_backend=settings.ocr_backend,
            ocr_device=settings.ocr_device,
            ocr_dpi=settings.ocr_dpi,
            crop_dir=settings.ocr_crop_dir,
            gemini_api_key=settings.gemini_api_key,
            gemini_ocr_model=settings.gemini_ocr_model,
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            llm_temp=settings.llm_temp,
            plagiarism_threshold=settings.plagiarism_threshold,
            use_embeddings=settings.plagiarism_embeddings,
            embedding_model=settings.embedding_model,
            storage_backend=settings.storage_backend,
            storage_kwargs=storage_kwargs,
        )
        _pipeline = GradeOpsPipeline(cfg)
    return _pipeline


# ─────────────────────────────────────────────
# Helper: parse rubrics from JSON string
# ─────────────────────────────────────────────

def _parse_rubrics(rubrics_json: str, exam_id: str) -> list[Rubric]:
    raw_list = _json.loads(rubrics_json)
    rubrics: list[Rubric] = []
    for raw in raw_list:
        raw = dict(raw)
        criteria_data = raw.pop("criteria", [])
        rubrics.append(Rubric(
            rubric_id=str(uuid.uuid4()),
            exam_id=exam_id,
            criteria=[RubricCriterion(**c) for c in criteria_data],
            **raw,
        ))
    return rubrics


# ─────────────────────────────────────────────
# Request body models
# ─────────────────────────────────────────────

class BulkApprovePayload(BaseModel):
    grade_ids: list[str]
    ta_id: str


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

# ── GET /exams  ───────────────────────────────
@router.get("/exams", summary="[Instructor] List all submitted exams")
async def list_exams(
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_instructor),
):
    try:
        batches = pipeline.storage.list_batches()
    except AttributeError:
        all_grades = pipeline.storage.load_grades(
            exam_id=None)  # type: ignore[arg-type]
        seen: dict[str, dict] = {}
        for g in all_grades:
            if g.exam_id not in seen:
                seen[g.exam_id] = {
                    "exam_id":       g.exam_id,
                    "course_id":     "—",
                    "student_count": 0,
                    "processed":     True,
                    "created_at":    None,
                }
            seen[g.exam_id]["student_count"] += 1
        batches = list(seen.values())
    return {"exams": batches}


# ── POST /exams  ──────────────────────────────
@router.post("/exams", summary="[Instructor] Submit exam PDFs + rubric for grading")
async def submit_exam(
    course_id:     Annotated[str, Form()],
    rubrics_json:  Annotated[str, Form()],
    pdfs:          list[UploadFile] = File(...),
    pipeline:      GradeOpsPipeline = Depends(get_pipeline),
    current_user:  UserORM = Depends(require_instructor),
):
    exam_id = str(uuid.uuid4())
    instructor_id = current_user.user_id   # always use the authenticated user's ID
    tmp_dir = tempfile.mkdtemp(prefix="gradeops_")
    pdf_paths: list[str] = []
    try:
        for upload in pdfs:
            dest = os.path.join(
                tmp_dir, upload.filename or f"{uuid.uuid4()}.pdf")
            content = await upload.read()
            with open(dest, "wb") as fh:
                fh.write(content)
            pdf_paths.append(dest)

        rubrics = _parse_rubrics(rubrics_json, exam_id)

        batch = ExamBatch(
            exam_id=exam_id,
            course_id=course_id,
            instructor_id=instructor_id,
            pdf_paths=pdf_paths,
            rubrics=rubrics,
            student_count=len(pdf_paths),
        )

        def _run_and_cleanup(b: ExamBatch) -> object:
            try:
                return pipeline.run_exam(b)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                logger.debug("Cleaned up temp dir: %s", tmp_dir)

        job_id = task_manager.submit(_run_and_cleanup, batch, exam_id=exam_id)
        logger.info("Exam submitted | exam_id=%s | job_id=%s | pdfs=%d",
                    exam_id, job_id, len(pdfs))

    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return {
        "exam_id": exam_id,
        "job_id":  job_id,
        "status":  JobStatus.QUEUED,
        "message": f"Processing {len(pdfs)} student PDF(s). Poll /jobs/{job_id} for status.",
    }


# ── GET /jobs/{job_id}  ───────────────────────
@router.get("/jobs/{job_id}", summary="Poll background job status")
async def get_job_status(
    job_id:       str,
    current_user: UserORM = Depends(require_ta_or_above),
):
    job = task_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


# ── GET /exams/{exam_id}/dashboard  ───────────
@router.get("/exams/{exam_id}/dashboard", summary="[TA+] TA review dashboard data")
async def get_dashboard(
    exam_id:      str,
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_ta_or_above),
):
    try:
        return pipeline.get_dashboard_data(exam_id)
    except Exception as exc:
        logger.exception("Dashboard error | exam_id=%s", exam_id)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /exams/{exam_id}/grades  ──────────────
@router.get("/exams/{exam_id}/grades", summary="[TA+] All grades for an exam")
async def get_grades(
    exam_id:         str,
    student_id:      str | None = None,
    question_number: int | None = None,
    pipeline:        GradeOpsPipeline = Depends(get_pipeline),
    current_user:    UserORM = Depends(require_ta_or_above),
):
    grades = pipeline.storage.load_grades(exam_id, student_id, question_number)
    return [g.model_dump() for g in grades]


# ── GET /exams/{exam_id}/grades/export  ───────
@router.get("/exams/{exam_id}/grades/export", summary="[Instructor] Export grades as CSV")
async def export_grades_csv(
    exam_id:      str,
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_instructor),
):
    grades = pipeline.storage.load_grades(exam_id)
    if not grades:
        raise HTTPException(
            status_code=404, detail="No grades found for this exam")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "student_id", "question_number", "total_awarded", "total_possible",
        "status", "plagiarism_flag", "plagiarism_similarity",
        "ta_override_score", "reviewed_by", "overall_justification",
    ])
    writer.writeheader()
    for g in grades:
        writer.writerow({
            "student_id":            g.student_id,
            "question_number":       g.question_number,
            "total_awarded":         g.total_awarded,
            "total_possible":        g.total_possible,
            "status":                g.status.value,
            "plagiarism_flag":       g.plagiarism_flag,
            "plagiarism_similarity": g.plagiarism_similarity,
            "ta_override_score":     g.ta_override_score or "",
            "reviewed_by":           g.reviewed_by or "",
            "overall_justification": g.overall_justification,
        })

    output.seek(0)
    filename = f"grades_{exam_id[:8]}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── POST /grades/review  ──────────────────────
@router.post("/grades/review", summary="[TA+] Approve or override an AI grade")
async def ta_review(
    exam_id:      str,
    payload:      TAReviewPayload,
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_ta_or_above),
):
    try:
        updated = pipeline.apply_ta_review(payload, exam_id=exam_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "ok", "grade_id": payload.grade_id, "action": payload.action,
            "updated_grade": updated.model_dump() if updated else None}


# ── POST /grades/review/bulk  ─────────────────
@router.post("/grades/review/bulk", summary="[TA+] Bulk approve multiple grades")
async def ta_bulk_approve(
    exam_id:      str,
    payload:      BulkApprovePayload,
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_ta_or_above),
):
    approved, skipped = [], []
    for gid in payload.grade_ids:
        try:
            pipeline.apply_ta_review(
                TAReviewPayload(
                    grade_id=gid, ta_id=payload.ta_id, action="approve"),
                exam_id=exam_id,
            )
            approved.append(gid)
        except Exception as exc:
            logger.warning("Bulk approve skipped grade %s: %s", gid, exc)
            skipped.append(gid)
    return {"approved": approved, "skipped": skipped}


# ── GET /exams/{exam_id}/plagiarism  ──────────
@router.get("/exams/{exam_id}/plagiarism", summary="[TA+] Plagiarism flags for an exam")
async def get_plagiarism_flags(
    exam_id:      str,
    min_score:    float = 0.0,
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_ta_or_above),
):
    grades = pipeline.storage.load_grades(exam_id)
    flagged = [
        g.model_dump()
        for g in grades
        if g.plagiarism_flag and g.plagiarism_similarity >= min_score
    ]
    return {"exam_id": exam_id, "flagged_count": len(flagged), "results": flagged}


# ── GET /students/{student_id}/grades  ────────
@router.get("/students/{student_id}/grades", summary="[TA+] All grades for a student in an exam")
async def get_student_grades(
    student_id:   str,
    exam_id:      str,
    pipeline:     GradeOpsPipeline = Depends(get_pipeline),
    current_user: UserORM = Depends(require_ta_or_above),
):
    grades = pipeline.storage.load_grades(exam_id, student_id=student_id)
    return [g.model_dump() for g in grades]


# ── GET /health  ──────────────────────────────
@router.get("/health", summary="Health check (no auth required)")
async def health():
    return {
        "status":  "ok",
        "service": "GradeOps",
        "version": settings.app_version,
    }
