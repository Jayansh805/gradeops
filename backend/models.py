"""
models.py — GradeOps Pydantic Schemas
All shared data structures used across the pipeline.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime, timezone


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class UserRole(str, Enum):
    INSTRUCTOR = "instructor"
    TA = "ta"

class GradeStatus(str, Enum):
    PENDING   = "pending"    # OCR done, not yet graded
    AI_GRADED = "ai_graded"  # AI graded, awaiting TA review
    APPROVED  = "approved"   # TA approved AI grade
    OVERRIDDEN = "overridden" # TA overrode AI grade
    FLAGGED   = "flagged"    # Flagged for plagiarism or review


# ─────────────────────────────────────────────
# Rubric
# ─────────────────────────────────────────────

class RubricCriterion(BaseModel):
    criterion_id: str
    description: str                   # e.g. "Correct use of Big-O notation"
    max_points: float
    required_keywords: list[str] = []  # keywords that must appear
    partial_credit: bool = True        # allow partial marks


class Rubric(BaseModel):
    rubric_id: str
    exam_id: str
    question_number: int
    total_points: float
    criteria: list[RubricCriterion]
    strict_mode: bool = False          # if True, no partial credit at all


# ─────────────────────────────────────────────
# OCR Output
# ─────────────────────────────────────────────

class OCRResult(BaseModel):
    student_id: str
    exam_id: str
    question_number: int
    raw_text: str                      # transcribed handwritten answer
    confidence: float = Field(ge=0.0, le=1.0)
    image_crop_path: str               # path to cropped image of this answer
    page_number: int
    # FIX #11: replaced deprecated datetime.utcnow with timezone-aware variant
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Grading
# ─────────────────────────────────────────────

class CriterionScore(BaseModel):
    criterion_id: str
    awarded_points: float
    justification: str                 # one-line reason from the LLM


class GradeResult(BaseModel):
    grade_id: str
    student_id: str
    exam_id: str
    question_number: int
    ocr_text: str
    rubric_id: str
    criterion_scores: list[CriterionScore]
    total_awarded: float
    total_possible: float
    overall_justification: str
    status: GradeStatus = GradeStatus.AI_GRADED
    plagiarism_flag: bool = False
    plagiarism_similarity: float = 0.0
    # FIX #11: replaced deprecated datetime.utcnow with timezone-aware variant
    graded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_by: str | None = None     # TA user_id if reviewed
    ta_override_score: float | None = None
    ta_override_note: str | None = None


# ─────────────────────────────────────────────
# Plagiarism
# ─────────────────────────────────────────────

class PlagiarismMatch(BaseModel):
    student_a: str
    student_b: str
    exam_id: str
    question_number: int
    similarity_score: float            # 0.0 – 1.0
    matched_phrases: list[str]
    flagged: bool                      # True if above threshold


# ─────────────────────────────────────────────
# Exam / Batch
# ─────────────────────────────────────────────

class ExamBatch(BaseModel):
    exam_id: str
    course_id: str
    instructor_id: str
    pdf_paths: list[str]               # uploaded PDF file paths
    rubrics: list[Rubric]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    student_count: int = 0
    processed: bool = False


class TAReviewPayload(BaseModel):
    grade_id: str
    ta_id: str
    # FIX: typed as Literal for compile-time safety instead of bare str
    action: Literal["approve", "override"]
    override_score: float | None = None
    override_note: str | None = None
