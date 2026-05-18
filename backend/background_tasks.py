"""
background_tasks.py — GradeOps Async Task Manager
Runs the heavy OCR + grading pipeline in a background thread so the
POST /exams endpoint returns immediately with a job_id.

Status flow:
    queued → running → completed
                     ↘ failed

Usage (inside an API route):
    from background_tasks import task_manager, JobStatus
    job_id = task_manager.submit(pipeline.run_exam, exam_batch)
    status = task_manager.get(job_id)
"""

import uuid
import logging
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Job status model
# ─────────────────────────────────────────────

class JobStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


@dataclass
class Job:
    job_id:     str
    exam_id:    str
    status:     JobStatus = JobStatus.QUEUED
    result:     Any       = None
    error:      str | None = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at:   datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "job_id":       self.job_id,
            "exam_id":      self.exam_id,
            "status":       self.status.value,
            "error":        self.error,
            "submitted_at": self.submitted_at.isoformat(),
            "started_at":   self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_summary": self.result.summary() if self.result and hasattr(self.result, "summary") else None,
        }


# ─────────────────────────────────────────────
# Task manager
# ─────────────────────────────────────────────

class TaskManager:
    """
    Thread-based background task runner with an in-memory job store.

    For production, swap out for Celery + Redis or FastAPI BackgroundTasks
    with a persistent store.
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        fn: Callable,
        *args,
        exam_id: str = "",
        **kwargs,
    ) -> str:
        """
        Submit a callable to run in a background thread.

        Args:
            fn:      The function to call (e.g., pipeline.run_exam).
            *args:   Positional arguments for fn.
            exam_id: Used to tag the job for status lookup.
            **kwargs: Keyword arguments for fn.

        Returns:
            job_id: UUID string to poll for status.
        """
        job_id = str(uuid.uuid4())
        job    = Job(job_id=job_id, exam_id=exam_id)

        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run,
            args=(job, fn, args, kwargs),
            daemon=True,
            name=f"gradeops-job-{job_id[:8]}",
        )
        thread.start()
        logger.info("Job submitted | job_id=%s exam_id=%s", job_id, exam_id)
        return job_id

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self, exam_id: str | None = None) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        if exam_id:
            jobs = [j for j in jobs if j.exam_id == exam_id]
        return sorted(jobs, key=lambda j: j.submitted_at, reverse=True)

    # ── internal ──────────────────────────────

    def _run(self, job: Job, fn: Callable, args: tuple, kwargs: dict) -> None:
        with self._lock:
            job.status     = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)

        logger.info("Job started | job_id=%s", job.job_id)
        try:
            result = fn(*args, **kwargs)
            with self._lock:
                job.status       = JobStatus.COMPLETED
                job.result       = result
                job.completed_at = datetime.now(timezone.utc)
            logger.info("Job completed | job_id=%s", job.job_id)
        except Exception as exc:
            logger.exception("Job FAILED | job_id=%s | error=%s", job.job_id, exc)
            with self._lock:
                job.status       = JobStatus.FAILED
                job.error        = str(exc)
                job.completed_at = datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

task_manager = TaskManager()
