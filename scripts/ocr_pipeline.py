"""
ocr_pipeline.py — GradeOps OCR Module
Extracts and transcribes handwritten answers from scanned exam PDFs.

Supported backends:
  - "qwen_vl"  : Qwen2-VL via HuggingFace (recommended for handwriting)
  - "nougat"   : Meta Nougat (better for printed/mixed content)
  - "mock"     : Returns dummy text (for testing without GPU)

Usage:
    pipeline = OCRPipeline(backend="qwen_vl")
    results  = pipeline.process_exam_pdf("exam_001", "student_42", "scan.pdf", num_questions=5)
"""

import os
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Literal

import fitz                        # PyMuPDF — pip install pymupdf
from PIL import Image
import numpy as np

from models import OCRResult

logger = logging.getLogger(__name__)

BackendType = Literal["qwen_vl", "nougat", "mock"]


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

@dataclass
class OCRConfig:
    backend: BackendType = "qwen_vl"
    device: str = "cuda"               # "cuda" | "cpu"
    crop_output_dir: str = "./crops"
    dpi: int = 200                     # PDF → image resolution
    confidence_threshold: float = 0.5  # below this → flag for manual review
    qwen_model_id: str = "Qwen/Qwen2-VL-7B-Instruct"
    nougat_model_id: str = "facebook/nougat-base"


# ─────────────────────────────────────────────
# Backend loaders (lazy — only loaded when needed)
# ─────────────────────────────────────────────

class _QwenVLBackend:
    """Wraps Qwen2-VL for handwriting transcription."""

    def __init__(self, model_id: str, device: str):
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
        import torch

        logger.info("Loading Qwen2-VL model: %s", model_id)
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map=device,
        )
        self.device = device

    def transcribe(self, image: Image.Image) -> tuple[str, float]:
        """Returns (transcribed_text, confidence_score)."""
        import torch

        prompt = (
            "This is a scanned handwritten student exam answer. "
            "Transcribe every word exactly as written, including any crossed-out text. "
            "Do not add explanations. Output only the transcribed text."
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text",  "text": prompt},
                ],
            }
        ]
        text_input = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text_input], images=[image], return_tensors="pt"
        ).to(self.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )
        generated = output_ids[:, inputs["input_ids"].shape[1]:]
        text = self.processor.batch_decode(generated, skip_special_tokens=True)[0]

        # Heuristic confidence: longer non-empty responses = higher confidence
        confidence = min(0.95, 0.5 + len(text.split()) * 0.01)
        return text.strip(), round(confidence, 3)


class _NougatBackend:
    """Wraps Meta Nougat for document transcription."""

    def __init__(self, model_id: str, device: str):
        from nougat import NougatModel
        from nougat.utils.checkpoint import get_checkpoint

        logger.info("Loading Nougat model: %s", model_id)
        checkpoint = get_checkpoint(model_id)
        self.model = NougatModel.from_pretrained(checkpoint).to(device)
        self.model.eval()
        self.device = device

    def transcribe(self, image: Image.Image) -> tuple[str, float]:
        import torch
        from nougat.utils.dataset import ImageDataset

        sample = ImageDataset.from_pil(image)
        with torch.no_grad():
            output = self.model.inference(image_tensors=sample.unsqueeze(0).to(self.device))
        text = output["predictions"][0]
        confidence = 0.80  # Nougat doesn't expose per-sample confidence
        return text.strip(), confidence


class _MockBackend:
    """Deterministic mock — safe to use without GPU."""

    def transcribe(self, image: Image.Image) -> tuple[str, float]:
        return (
            "The time complexity of the algorithm is O(n log n) because the merge sort "
            "recursively divides the array and merges in linear time.",
            0.92,
        )


# ─────────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────────

class OCRPipeline:
    """
    Full OCR pipeline: PDF → page images → per-question crops → transcription.

    Args:
        config: OCRConfig instance (or uses defaults).
    """

    def __init__(self, config: OCRConfig | None = None):
        self.cfg = config or OCRConfig()
        Path(self.cfg.crop_output_dir).mkdir(parents=True, exist_ok=True)
        self._backend = self._load_backend()

    # ── public ────────────────────────────────

    def process_exam_pdf(
        self,
        exam_id: str,
        student_id: str,
        pdf_path: str,
        num_questions: int,
        question_regions: list[dict] | None = None,
    ) -> list[OCRResult]:
        """
        Process one student's PDF exam.

        Args:
            exam_id:          Unique exam identifier.
            student_id:       Student identifier.
            pdf_path:         Local path to the scanned PDF.
            num_questions:    Number of questions to extract.
            question_regions: Optional list of dicts with keys
                              {page, x0, y0, x1, y1} per question.
                              If None, splits each page evenly.

        Returns:
            List of OCRResult, one per question.
        """
        pages = self._pdf_to_images(pdf_path)
        results: list[OCRResult] = []

        for q_num in range(1, num_questions + 1):
            region = question_regions[q_num - 1] if question_regions else None
            crop, page_num = self._extract_question_crop(pages, q_num, num_questions, region)

            crop_path = self._save_crop(crop, exam_id, student_id, q_num)
            text, confidence = self._backend.transcribe(crop)

            if confidence < self.cfg.confidence_threshold:
                logger.warning(
                    "Low OCR confidence %.2f for student=%s q=%d — may need manual check",
                    confidence, student_id, q_num,
                )

            results.append(
                OCRResult(
                    student_id=student_id,
                    exam_id=exam_id,
                    question_number=q_num,
                    raw_text=text,
                    confidence=confidence,
                    image_crop_path=crop_path,
                    page_number=page_num,
                )
            )
            logger.debug("OCR q%d | student=%s | conf=%.2f | chars=%d",
                         q_num, student_id, confidence, len(text))

        return results

    def process_exam_batch(
        self,
        exam_id: str,
        pdf_paths: dict[str, str],   # {student_id: pdf_path}
        num_questions: int,
        question_regions: list[dict] | None = None,
    ) -> dict[str, list[OCRResult]]:
        """Process PDFs for all students in a batch."""
        all_results: dict[str, list[OCRResult]] = {}
        for student_id, pdf_path in pdf_paths.items():
            logger.info("Processing OCR for student %s …", student_id)
            all_results[student_id] = self.process_exam_pdf(
                exam_id, student_id, pdf_path, num_questions, question_regions
            )
        return all_results

    # ── private ───────────────────────────────

    def _load_backend(self):
        b = self.cfg.backend
        if b == "qwen_vl":
            return _QwenVLBackend(self.cfg.qwen_model_id, self.cfg.device)
        elif b == "nougat":
            return _NougatBackend(self.cfg.nougat_model_id, self.cfg.device)
        elif b == "mock":
            return _MockBackend()
        raise ValueError(f"Unknown OCR backend: {b}")

    def _pdf_to_images(self, pdf_path: str) -> list[Image.Image]:
        """Convert each PDF page to a PIL Image."""
        doc = fitz.open(pdf_path)
        images = []
        mat = fitz.Matrix(self.cfg.dpi / 72, self.cfg.dpi / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        doc.close()
        return images

    def _extract_question_crop(
        self,
        pages: list[Image.Image],
        q_num: int,
        total_questions: int,
        region: dict | None,
    ) -> tuple[Image.Image, int]:
        """
        Crop the image region for question q_num.
        If no region provided, divides each page equally.
        """
        if region:
            page_idx = region["page"] - 1
            img = pages[min(page_idx, len(pages) - 1)]
            crop = img.crop((region["x0"], region["y0"], region["x1"], region["y1"]))
            return crop, page_idx + 1

        # Fallback: one question per equal vertical strip on page 0
        page_idx = min(q_num - 1, len(pages) - 1)
        img = pages[page_idx]
        w, h = img.size
        strip_h = h // total_questions
        y0 = (q_num - 1) * strip_h
        y1 = y0 + strip_h
        return img.crop((0, y0, w, y1)), page_idx + 1

    def _save_crop(self, crop: Image.Image, exam_id: str, student_id: str, q_num: int) -> str:
        fname = f"{exam_id}_{student_id}_q{q_num}_{uuid.uuid4().hex[:6]}.png"
        path = os.path.join(self.cfg.crop_output_dir, fname)
        crop.save(path)
        return path
