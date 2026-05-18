"""
storage.py — GradeOps Storage Abstraction
Handles persistence of exam PDFs, cropped images, and grade records.

Backends:
  - "local"  : saves files to disk, grades to a JSON file (dev/testing)
  - "s3"     : AWS S3 for files + DynamoDB for grade records
  - "gcs"    : Google Cloud Storage (not yet implemented)

Usage:
    store  = StorageBackend.create("local", base_dir="./gradeops_data")
    store.save_pdf("exam_01", "student_42", "/tmp/scan.pdf")
    store.save_grade(grade_result)
    grades = store.load_grades(exam_id="exam_01")
"""

import os
import json
import shutil
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import Literal

from models import GradeResult, OCRResult, ExamBatch

logger = logging.getLogger(__name__)

BackendType = Literal["local", "s3"]   # FIX #16: removed "gcs" — not implemented


# ─────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────

class BaseStorage(ABC):

    @abstractmethod
    def save_pdf(self, exam_id: str, student_id: str, local_path: str) -> str:
        """Upload/copy PDF. Returns the stored URI."""

    @abstractmethod
    def save_crop(self, local_image_path: str) -> str:
        """Upload/copy answer-crop image. Returns the stored URI."""

    @abstractmethod
    def save_grade(self, grade: GradeResult) -> None:
        """Persist a GradeResult."""

    @abstractmethod
    def save_ocr(self, ocr: OCRResult) -> None:
        """Persist an OCRResult."""

    # FIX #15: bulk helpers promoted to the abstract base so all backends
    # must implement (or inherit) them — no more hasattr() duck-typing.
    def save_grades_bulk(self, grades: list[GradeResult]) -> None:
        """Persist multiple GradeResults. Override for efficiency."""
        for g in grades:
            self.save_grade(g)

    def save_ocr_bulk(self, ocr_list: list[OCRResult]) -> None:
        """Persist multiple OCRResults. Override for efficiency."""
        for o in ocr_list:
            self.save_ocr(o)

    @abstractmethod
    def load_grades(
        self,
        exam_id: str,
        student_id: str | None = None,
        question_number: int | None = None,
    ) -> list[GradeResult]:
        """Retrieve GradeResult records with optional filters."""

    @abstractmethod
    def load_ocr(self, exam_id: str, student_id: str | None = None) -> list[OCRResult]:
        """Retrieve OCRResult records."""

    # FIX #2: added exam_id as an explicit parameter so S3Storage can build
    # the DynamoDB key without smuggling it inside the updates dict.
    @abstractmethod
    def update_grade(self, grade_id: str, updates: dict, exam_id: str | None = None) -> None:
        """Partially update a grade record (e.g., TA review)."""


# ─────────────────────────────────────────────
# Local backend (JSON files + local filesystem)
# ─────────────────────────────────────────────

class LocalStorage(BaseStorage):
    """
    Flat-file storage for development and CI/CD.

    Directory layout:
        base_dir/
          pdfs/<exam_id>/<student_id>.pdf
          crops/<filename>
          db/grades.json
          db/ocr.json
    """

    def __init__(self, base_dir: str = "./gradeops_data"):
        self.base   = Path(base_dir)
        self.pdfs   = self.base / "pdfs"
        self.crops  = self.base / "crops"
        self.db     = self.base / "db"

        for d in [self.pdfs, self.crops, self.db]:
            d.mkdir(parents=True, exist_ok=True)

        self._grades_path = self.db / "grades.json"
        self._ocr_path    = self.db / "ocr.json"
        # Thread lock — prevents race conditions when background jobs
        # write grades concurrently (TaskManager uses threads).
        self._lock = threading.Lock()

        if not self._grades_path.exists():
            self._grades_path.write_text("[]")
        if not self._ocr_path.exists():
            self._ocr_path.write_text("[]")

    # ── file ops ──────────────────────────────

    def save_pdf(self, exam_id: str, student_id: str, local_path: str) -> str:
        dest_dir = self.pdfs / exam_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{student_id}.pdf"
        shutil.copy2(local_path, dest)
        logger.debug("Saved PDF → %s", dest)
        return str(dest)

    def save_crop(self, local_image_path: str) -> str:
        fname = Path(local_image_path).name
        dest  = self.crops / fname
        shutil.copy2(local_image_path, dest)
        return str(dest)

    # ── grade ops ─────────────────────────────

    def save_grade(self, grade: GradeResult) -> None:
        with self._lock:
            records = self._read_json(self._grades_path)
            records.append(grade.model_dump(mode="json"))
            self._write_json(self._grades_path, records)

    def save_grades_bulk(self, grades: list[GradeResult]) -> None:
        """Single read-write for the entire batch — more efficient than looping save_grade."""
        with self._lock:
            records = self._read_json(self._grades_path)
            records.extend(g.model_dump(mode="json") for g in grades)
            self._write_json(self._grades_path, records)

    def load_grades(
        self,
        exam_id: str,
        student_id: str | None = None,
        question_number: int | None = None,
    ) -> list[GradeResult]:
        with self._lock:
            records = self._read_json(self._grades_path)
        filtered = [r for r in records if r["exam_id"] == exam_id]
        if student_id:
            filtered = [r for r in filtered if r["student_id"] == student_id]
        if question_number is not None:
            filtered = [r for r in filtered if r["question_number"] == question_number]
        return [GradeResult(**r) for r in filtered]

    def list_batches(self) -> list[dict]:
        """Return a summary list of all unique exams derived from stored grades."""
        with self._lock:
            records = self._read_json(self._grades_path)
        seen: dict[str, dict] = {}
        for r in records:
            eid = r["exam_id"]
            if eid not in seen:
                seen[eid] = {
                    "exam_id":       eid,
                    "course_id":     r.get("course_id", "—"),
                    "student_count": 0,
                    "processed":     True,
                    "created_at":    None,
                }
            seen[eid]["student_count"] += 1
        return list(seen.values())

    # FIX #2: exam_id param added to match updated abstract signature
    def update_grade(self, grade_id: str, updates: dict, exam_id: str | None = None) -> None:
        with self._lock:
            records = self._read_json(self._grades_path)
            for rec in records:
                if rec["grade_id"] == grade_id:
                    rec.update(updates)
                    break
            self._write_json(self._grades_path, records)

    # ── ocr ops ───────────────────────────────

    def save_ocr(self, ocr: OCRResult) -> None:
        with self._lock:
            records = self._read_json(self._ocr_path)
            records.append(ocr.model_dump(mode="json"))
            self._write_json(self._ocr_path, records)

    def save_ocr_bulk(self, ocr_list: list[OCRResult]) -> None:
        """Single read-write for the entire batch."""
        with self._lock:
            records = self._read_json(self._ocr_path)
            records.extend(o.model_dump(mode="json") for o in ocr_list)
            self._write_json(self._ocr_path, records)

    def load_ocr(self, exam_id: str, student_id: str | None = None) -> list[OCRResult]:
        with self._lock:
            records = self._read_json(self._ocr_path)
        filtered = [r for r in records if r["exam_id"] == exam_id]
        if student_id:
            filtered = [r for r in filtered if r["student_id"] == student_id]
        return [OCRResult(**r) for r in filtered]

    # ── helpers ───────────────────────────────

    def _read_json(self, path: Path) -> list[dict]:
        # Lock is held by the caller (all write paths hold it); reads are also
        # guarded here so a concurrent write never races with a read.
        return json.loads(path.read_text())

    def _write_json(self, path: Path, data: list[dict]) -> None:
        # Atomic write via a temp file to avoid partial-write corruption.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, default=str, indent=2))
        tmp.replace(path)


# ─────────────────────────────────────────────
# S3 backend (AWS)
# ─────────────────────────────────────────────

class S3Storage(BaseStorage):
    """
    AWS S3 (files) + DynamoDB (grade/ocr records).
    Requires: boto3, correct IAM permissions.

    Args:
        bucket:       S3 bucket name.
        dynamo_table: DynamoDB table name for grade+ocr records.
        region:       AWS region.
    """

    def __init__(self, bucket: str, dynamo_table: str, region: str = "us-east-1"):
        import boto3
        self.bucket = bucket
        self.table  = dynamo_table
        self.s3     = boto3.client("s3", region_name=region)
        self.dynamo = boto3.resource("dynamodb", region_name=region).Table(dynamo_table)

    def save_pdf(self, exam_id: str, student_id: str, local_path: str) -> str:
        key = f"pdfs/{exam_id}/{student_id}.pdf"
        self.s3.upload_file(local_path, self.bucket, key)
        uri = f"s3://{self.bucket}/{key}"
        logger.debug("Uploaded PDF → %s", uri)
        return uri

    def save_crop(self, local_image_path: str) -> str:
        fname = Path(local_image_path).name
        key   = f"crops/{fname}"
        self.s3.upload_file(local_image_path, self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def save_grade(self, grade: GradeResult) -> None:
        item = grade.model_dump(mode="json")
        item["pk"] = f"GRADE#{grade.exam_id}"
        item["sk"] = grade.grade_id
        self.dynamo.put_item(Item=item)

    def save_ocr(self, ocr: OCRResult) -> None:
        item = ocr.model_dump(mode="json")
        item["pk"] = f"OCR#{ocr.exam_id}"
        item["sk"] = f"{ocr.student_id}#Q{ocr.question_number}"
        self.dynamo.put_item(Item=item)

    def load_grades(
        self,
        exam_id: str,
        student_id: str | None = None,
        question_number: int | None = None,
    ) -> list[GradeResult]:
        from boto3.dynamodb.conditions import Key
        # FIX #8: paginate DynamoDB queries to avoid silently truncated results
        items: list[dict] = []
        kwargs = {"KeyConditionExpression": Key("pk").eq(f"GRADE#{exam_id}")}
        while True:
            resp = self.dynamo.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last

        if student_id:
            items = [i for i in items if i.get("student_id") == student_id]
        if question_number is not None:
            items = [i for i in items if i.get("question_number") == question_number]
        return [GradeResult(**{k: v for k, v in i.items() if k not in ("pk", "sk")})
                for i in items]

    # FIX #2: exam_id is now an explicit parameter instead of being smuggled
    # inside the updates dict via the "_exam_id" hack.
    def update_grade(self, grade_id: str, updates: dict, exam_id: str | None = None) -> None:
        if not exam_id:
            raise ValueError("exam_id is required for S3Storage.update_grade")
        expr    = "SET " + ", ".join(f"#{k}=:{k}" for k in updates)
        names   = {f"#{k}": k for k in updates}
        values  = {f":{k}": v for k, v in updates.items()}
        self.dynamo.update_item(
            Key={"pk": f"GRADE#{exam_id}", "sk": grade_id},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def load_ocr(self, exam_id: str, student_id: str | None = None) -> list[OCRResult]:
        from boto3.dynamodb.conditions import Key
        # FIX #8: paginate DynamoDB queries
        items: list[dict] = []
        kwargs = {"KeyConditionExpression": Key("pk").eq(f"OCR#{exam_id}")}
        while True:
            resp = self.dynamo.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last

        if student_id:
            items = [i for i in items if i.get("student_id") == student_id]
        return [OCRResult(**{k: v for k, v in i.items() if k not in ("pk", "sk")})
                for i in items]


# ─────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────

class StorageBackend:
    @staticmethod
    def create(backend: BackendType, **kwargs) -> BaseStorage:
        """
        Factory method.

        Examples:
            StorageBackend.create("local", base_dir="./data")
            StorageBackend.create("s3", bucket="my-bucket", dynamo_table="grades", region="us-east-1")
        """
        if backend == "local":
            return LocalStorage(**kwargs)
        elif backend == "s3":
            return S3Storage(**kwargs)
        raise ValueError(f"Unknown storage backend: {backend!r}. Valid options: 'local', 's3'.")
