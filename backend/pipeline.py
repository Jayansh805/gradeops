"""
pipeline.py — GradeOps Master Orchestrator
Wires OCR → Grading → Plagiarism → Storage into a single callable pipeline.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from models import (
    ExamBatch, Rubric, OCRResult, GradeResult,
    PlagiarismMatch, TAReviewPayload, GradeStatus
)
from ocr_pipeline import OCRPipeline, OCRConfig
from grading_agent import GradingAgent
from plagiarism_detector import PlagiarismDetector, PlagiarismConfig
from storage import StorageBackend, BaseStorage

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

@dataclass
class PipelineConfig:
    # OCR
    ocr_backend:   str = "gemini"   # gemini | qwen_vl | nougat | mock      # "qwen_vl" | "nougat" | "gemini" | "mock"
    ocr_device:    str = "cpu"
    crop_dir:      str = "./crops"
    ocr_dpi:       int = 200
    gemini_api_key:   str = ""          # required when ocr_backend = "gemini"
    gemini_ocr_model: str = "gemini-2.0-flash"  # change to gemini-1.5-pro for higher accuracy

    # Grading LLM
    # "openai" | "anthropic" | "together" | "gemini" | "mock"
    llm_provider:  str = "gemini"  # gemini | openai | anthropic | together | mock
    llm_model:     str = "gemini-2.0-flash"
    llm_temp:      float = 0.0

    # Plagiarism
    plagiarism_threshold: float = 0.82
    use_embeddings:       bool = False
    embedding_model:      str = "all-MiniLM-L6-v2"

    # Storage
    storage_backend: str = "local"
    storage_kwargs:  dict = field(default_factory=dict)


# ─────────────────────────────────────────────
# Exam report
# ─────────────────────────────────────────────

@dataclass
class ExamReport:
    exam_id: str
    total_students: int
    total_questions: int
    grades: list[GradeResult]
    plagiarism_flags: list[PlagiarismMatch]
    ocr_results: list[OCRResult]

    def summary(self) -> dict:
        avg = (
            sum(g.total_awarded for g in self.grades) / len(self.grades)
            if self.grades else 0.0
        )
        return {
            "exam_id":          self.exam_id,
            "students":         self.total_students,
            "questions":        self.total_questions,
            "grades_generated": len(self.grades),
            "plagiarism_flags": len(self.plagiarism_flags),
            "average_score":    round(avg, 2),
        }


# ─────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────

class GradeOpsPipeline:

    def __init__(self, config: PipelineConfig | None = None):
        self.cfg = config or PipelineConfig()

        # Initialise OCR — pass gemini_api_key when using gemini backend
        self.ocr = OCRPipeline(OCRConfig(
            backend=self.cfg.ocr_backend,
            device=self.cfg.ocr_device,
            crop_output_dir=self.cfg.crop_dir,
            dpi=self.cfg.ocr_dpi,
            gemini_api_key=self.cfg.gemini_api_key,
            gemini_ocr_model=self.cfg.gemini_ocr_model,
        ))

        self.grader = GradingAgent(
            llm_provider=self.cfg.llm_provider,
            model_name=self.cfg.llm_model,
            temperature=self.cfg.llm_temp,
        )
        self.plagiarism = PlagiarismDetector(PlagiarismConfig(
            threshold=self.cfg.plagiarism_threshold,
            use_embeddings=self.cfg.use_embeddings,
            embedding_model=self.cfg.embedding_model,
        ))
        self.storage: BaseStorage = StorageBackend.create(
            self.cfg.storage_backend, **self.cfg.storage_kwargs
        )

    # ── main entry point ──────────────────────

    def run_exam(self, exam_batch: ExamBatch) -> ExamReport:
        exam_id = exam_batch.exam_id
        num_questions = len(exam_batch.rubrics)
        rubric_map = {r.question_number: r for r in exam_batch.rubrics}

        pdf_paths: dict[str, str] = {}
        for p in exam_batch.pdf_paths:
            stem = Path(p).stem
            if not stem:
                logger.warning(
                    "Could not extract student_id from path %s — skipping.", p)
                continue
            if stem in pdf_paths:
                logger.warning(
                    "Duplicate student_id '%s' — later file wins.", stem)
            pdf_paths[stem] = p

        logger.info("=== GradeOps pipeline START | exam=%s | students=%d ===",
                    exam_id, len(pdf_paths))

        # ── Step 1: OCR ──────────────────────
        logger.info("[1/4] Running OCR with %s backend…", self.cfg.ocr_backend)
        all_ocr: list[OCRResult] = []
        for student_id, pdf_path in pdf_paths.items():
            results = self.ocr.process_exam_pdf(
                exam_id, student_id, pdf_path, num_questions
            )
            all_ocr.extend(results)
        self.storage.save_ocr_bulk(all_ocr)
        logger.info("OCR complete. Records: %d", len(all_ocr))

        # ── Step 2: Grading ───────────────────
        logger.info("[2/4] Grading answers with %s…", self.cfg.llm_provider)
        all_grades: list[GradeResult] = self.grader.grade_batch(
            all_ocr, rubric_map)
        logger.info("Grading complete. Records: %d", len(all_grades))

        # ── Step 3: Plagiarism ────────────────
        logger.info("[3/4] Scanning for plagiarism…")
        plag_report = self.plagiarism.full_report(all_ocr)
        flags = self.plagiarism.flagged_pairs(plag_report)

        flagged_students: set[tuple[str, int]] = set()
        for flag in flags:
            flagged_students.add((flag.student_a, flag.question_number))
            flagged_students.add((flag.student_b, flag.question_number))

        for grade in all_grades:
            key = (grade.student_id, grade.question_number)
            if key in flagged_students:
                grade.plagiarism_flag = True
                grade.status = GradeStatus.FLAGGED
                for flag in flags:
                    if (flag.student_a == grade.student_id or
                        flag.student_b == grade.student_id) and \
                       flag.question_number == grade.question_number:
                        grade.plagiarism_similarity = max(
                            grade.plagiarism_similarity, flag.similarity_score
                        )

        logger.info("Plagiarism scan complete. Flagged pairs: %d", len(flags))

        # ── Step 4: Persist grades ────────────
        logger.info("[4/4] Persisting grades…")
        self.storage.save_grades_bulk(all_grades)

        report = ExamReport(
            exam_id=exam_id,
            total_students=len(pdf_paths),
            total_questions=num_questions,
            grades=all_grades,
            plagiarism_flags=flags,
            ocr_results=all_ocr,
        )
        logger.info("=== Pipeline COMPLETE | %s ===", report.summary())
        return report

    # ── TA review ─────────────────────────────

    def apply_ta_review(self, payload: TAReviewPayload, exam_id: str) -> GradeResult | None:
        if payload.action == "approve":
            updates = {
                "status":      GradeStatus.APPROVED.value,
                "reviewed_by": payload.ta_id,
            }
        elif payload.action == "override":
            if payload.override_score is None:
                raise ValueError("override_score required for override action")
            updates = {
                "status":             GradeStatus.OVERRIDDEN.value,
                "reviewed_by":        payload.ta_id,
                "ta_override_score":  payload.override_score,
                "ta_override_note":   payload.override_note or "",
            }
        else:
            raise ValueError(f"Unknown action: {payload.action}")

        self.storage.update_grade(payload.grade_id, updates, exam_id=exam_id)
        logger.info("TA review applied | grade=%s | action=%s | ta=%s",
                    payload.grade_id, payload.action, payload.ta_id)

        grades = self.storage.load_grades(exam_id)
        return next((g for g in grades if g.grade_id == payload.grade_id), None)

    # ── convenience queries ───────────────────

    def get_dashboard_data(self, exam_id: str) -> dict[str, Any]:
        grades = self.storage.load_grades(exam_id)
        ocr = self.storage.load_ocr(exam_id)
        ocr_map = {(o.student_id, o.question_number): o for o in ocr}

        pending = [g for g in grades if g.status in
                   (GradeStatus.AI_GRADED, GradeStatus.FLAGGED)]

        dashboard = {
            "exam_id":      exam_id,
            "total_grades": len(grades),
            "pending":      len(pending),
            "items": [
                {
                    "grade": g.model_dump(),
                    "crop_path": (
                        "/crops/" + os.path.basename(
                            ocr_map[(g.student_id, g.question_number)
                                    ].image_crop_path
                        )
                        if (g.student_id, g.question_number) in ocr_map
                        and ocr_map[(g.student_id, g.question_number)].image_crop_path
                        else None
                    ),
                }
                for g in pending
            ],
        }
        return dashboard
