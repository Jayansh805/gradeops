"""
ocr_pipeline.py — GradeOps OCR Module
Extracts and transcribes handwritten answers from scanned exam PDFs.

Supported backends:
  - "gemini"   : Google Gemini Vision API (no GPU needed) ← recommended
  - "qwen_vl"  : Qwen2-VL via HuggingFace (requires GPU)
  - "nougat"   : Meta Nougat (requires GPU, better for printed content)
  - "mock"     : Returns dummy text (for testing without any API key)

Usage:
    pipeline = OCRPipeline(backend="gemini")
    results  = pipeline.process_exam_pdf("exam_001", "student_42", "scan.pdf", num_questions=5)
"""

import os
import time
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

import fitz                        # PyMuPDF — pip install pymupdf
from PIL import Image

from models import OCRResult

logger = logging.getLogger(__name__)

BackendType = Literal["qwen_vl", "nougat", "gemini", "mock"]


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

@dataclass
class OCRConfig:
    backend: BackendType = "gemini"    # default: gemini (no GPU needed)
    device: str = "auto"               # "auto" | "cuda" | "cpu" (only used by qwen_vl/nougat)
    crop_output_dir: str = "./crops"
    dpi: int = 200                     # PDF → image resolution
    confidence_threshold: float = 0.5  # below this → flag for manual review
    # Default to the 2B variant — fits in ~5 GB VRAM with fp16 (RTX 2050 etc.).
    # Switch to "Qwen/Qwen2-VL-7B-Instruct" if you have ≥16 GB VRAM.
    qwen_model_id: str = "Qwen/Qwen2-VL-2B-Instruct"
    nougat_model_id: str = "facebook/nougat-base"
    # Falls back to GEMINI_API_KEY env var if not passed explicitly
    gemini_api_key: str = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY", "")
    )
    # Configurable Gemini model — change to "gemini-1.5-pro" for better accuracy
    gemini_ocr_model: str = "gemini-2.0-flash"


# ─────────────────────────────────────────────
# Backend loaders (lazy — only loaded when needed)
# ─────────────────────────────────────────────

class _QwenVLBackend:
    """Wraps Qwen2-VL for handwriting transcription. Requires GPU."""

    def __init__(self, model_id: str, device: str):
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
        import torch

        logger.info("Loading Qwen2-VL model: %s (device=%s)", model_id, device)
        # Cap image resolution to bound the vision-tower activation memory on
        # small GPUs (a full-page crop can otherwise OOM a 4 GB card). max_pixels
        # ~= 1280 visual tokens, plenty for a single handwritten answer crop.
        self.processor = AutoProcessor.from_pretrained(
            model_id,
            min_pixels=256 * 28 * 28,
            max_pixels=1280 * 28 * 28,
        )
        if device == "cuda":
            # 2B in fp16 (~4 GB weights) doesn't fully fit in 4 GB VRAM. Let
            # accelerate keep most layers on the GPU and offload the overflow to
            # CPU RAM. max_memory reserves VRAM headroom for the vision tower and
            # generation activations so the forward pass doesn't OOM.
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_id,
                dtype=torch.float16,
                device_map="auto",
                max_memory={0: "3GiB", "cpu": "16GiB"},
                low_cpu_mem_usage=True,
            )
            self.input_device = "cuda"
        else:
            # CPU path: bfloat16 halves weight memory (~4 GB vs ~8 GB fp32).
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_id,
                dtype=torch.bfloat16,
                low_cpu_mem_usage=True,
            ).to(device)
            self.input_device = device
        self.model.eval()
        self.device = device

    def transcribe(self, image: Image.Image) -> tuple[str, float]:
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
        ).to(self.input_device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )
        generated = output_ids[:, inputs["input_ids"].shape[1]:]
        text = self.processor.batch_decode(
            generated, skip_special_tokens=True)[0]

        confidence = min(0.95, 0.5 + len(text.split()) * 0.01)
        return text.strip(), round(confidence, 3)


class _NougatBackend:
    """Wraps Meta Nougat for document transcription. Requires GPU."""

    def __init__(self, model_id: str, device: str):
        from transformers import NougatProcessor, VisionEncoderDecoderModel
        import torch

        logger.info("Loading Nougat model: %s", model_id)
        self.processor = NougatProcessor.from_pretrained(model_id)
        self.model = VisionEncoderDecoderModel.from_pretrained(
            model_id).to(device)
        self.model.eval()
        self.device = device

    def transcribe(self, image: Image.Image) -> tuple[str, float]:
        import torch

        pixel_values = self.processor(
            image, return_tensors="pt").pixel_values.to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                pixel_values,
                min_length=1,
                max_new_tokens=512,
                bad_words_ids=[[self.processor.tokenizer.unk_token_id]],
            )
        text = self.processor.batch_decode(
            outputs, skip_special_tokens=True)[0]
        confidence = 0.80
        return text.strip(), confidence


class _GeminiBackend:
    """
    Wraps Google Gemini Vision API for handwriting transcription.
    No GPU required — uses gemini-2.0-flash (fast, cheap, accurate).
    """

    # Slight delay between API calls to avoid hitting rate limits
    _RATE_LIMIT_SLEEP_SECONDS = 0.4

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        if not api_key:
            raise ValueError(
                "Gemini API key is required for the gemini OCR backend. "
                "Set GEMINI_API_KEY in your .env file."
            )
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)
        logger.info("Gemini Vision backend initialized (%s).", model)

    def transcribe(self, image: Image.Image) -> tuple[str, float]:
        import io
        import google.generativeai as genai

        # Convert PIL image to bytes
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        image_bytes = buf.read()

        # Create image part for Gemini
        image_part = {
            "mime_type": "image/png",
            "data": image_bytes
        }

        prompt = (
            "This is a scanned handwritten student exam answer sheet. "
            "Transcribe exactly what is handwritten, word for word. "
            "Include all answers you can see. "
            "Output only the transcribed text, nothing else."
        )

        response = self.model.generate_content([prompt, image_part])
        text = response.text.strip()

        # Gemini does not return a numeric confidence score.
        # We estimate it from response length: longer coherent answers
        # are generally more reliable. Capped at 0.92.
        word_count = len(text.split())
        confidence = round(min(0.92, 0.70 + word_count * 0.005), 3)

        # Respect Gemini free-tier rate limits (15 RPM)
        time.sleep(self._RATE_LIMIT_SLEEP_SECONDS)

        return text, confidence


class _MockBackend:
    """Deterministic mock — safe to use without GPU or API key."""

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
        if question_regions and len(question_regions) < num_questions:
            logger.warning(
                "question_regions has %d entries but num_questions=%d; "
                "falling back to auto-split for missing regions.",
                len(question_regions), num_questions,
            )

        pages = self._pdf_to_images(pdf_path)
        results: list[OCRResult] = []

        for q_num in range(1, num_questions + 1):
            region = (
                question_regions[q_num - 1]
                if question_regions and q_num - 1 < len(question_regions)
                else None
            )
            crop, page_num = self._extract_question_crop(
                pages, q_num, num_questions, region)

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
        pdf_paths: dict[str, str],
        num_questions: int,
        question_regions: list[dict] | None = None,
    ) -> dict[str, list[OCRResult]]:
        all_results: dict[str, list[OCRResult]] = {}
        for student_id, pdf_path in pdf_paths.items():
            logger.info("Processing OCR for student %s …", student_id)
            all_results[student_id] = self.process_exam_pdf(
                exam_id, student_id, pdf_path, num_questions, question_regions
            )
        return all_results

    # ── private ───────────────────────────────

    def _resolve_device(self) -> str:
        """Resolve cfg.device. 'auto' picks CUDA if available, else CPU."""
        requested = self.cfg.device
        if requested != "auto":
            return requested
        try:
            import torch
            if torch.cuda.is_available():
                logger.info("CUDA detected — using GPU for local OCR.")
                return "cuda"
        except ImportError:
            pass
        logger.info("No CUDA available — local OCR will run on CPU (expect slow inference).")
        return "cpu"

    def _load_backend(self):
        b = self.cfg.backend
        if b == "qwen_vl":
            try:
                return _QwenVLBackend(self.cfg.qwen_model_id, self._resolve_device())
            except ImportError as e:
                raise RuntimeError(
                    "qwen_vl backend requires 'torch', 'torchvision', and 'transformers'. "
                    "Install with: pip install torch torchvision transformers accelerate"
                ) from e
        elif b == "nougat":
            try:
                return _NougatBackend(self.cfg.nougat_model_id, self._resolve_device())
            except ImportError as e:
                raise RuntimeError(
                    "nougat backend requires 'torch', 'transformers', and 'sentencepiece'. "
                    "Install with: pip install torch transformers accelerate sentencepiece protobuf"
                ) from e
        elif b == "gemini":
            return _GeminiBackend(self.cfg.gemini_api_key, self.cfg.gemini_ocr_model)
        elif b == "mock":
            return _MockBackend()
        raise ValueError(f"Unknown OCR backend: {b!r}")

    def _pdf_to_images(self, pdf_path: str) -> list[Image.Image]:
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
        if region:
            page_idx = region["page"] - 1
            img = pages[min(page_idx, len(pages) - 1)]
            crop = img.crop((region["x0"], region["y0"],
                            region["x1"], region["y1"]))
            return crop, page_idx + 1

        num_pages = len(pages)

        if num_pages >= total_questions:
            page_idx = min(q_num - 1, num_pages - 1)
            return pages[page_idx], page_idx + 1

        questions_per_page = total_questions / num_pages
        page_idx = min(int((q_num - 1) / questions_per_page), num_pages - 1)
        img = pages[page_idx]
        w, h = img.size

        first_q_on_page = int(page_idx * questions_per_page)
        q_on_page = q_num - 1 - first_q_on_page
        qs_on_this_page = round(questions_per_page) or 1
        strip_h = h // qs_on_this_page
        y0 = q_on_page * strip_h
        y1 = min(y0 + strip_h, h)

        if y0 >= h:
            logger.warning(
                "Crop y0=%d >= page height=%d for q%d — clamping to last strip.",
                y0, h, q_num,
            )
            y0 = max(0, h - strip_h)
            y1 = h

        return img.crop((0, y0, w, y1)), page_idx + 1

    def _save_crop(self, crop: Image.Image, exam_id: str, student_id: str, q_num: int) -> str:
        fname = f"{exam_id}_{student_id}_q{q_num}_{uuid.uuid4().hex[:6]}.png"
        path = os.path.join(self.cfg.crop_output_dir, fname)
        crop.save(path)
        return path
