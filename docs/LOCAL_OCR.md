# Local OCR (Qwen2-VL-2B) — Setup & Notes

GradeOps can run OCR locally with **Qwen2-VL-2B-Instruct**, a vision-language model
that reads handwriting, instead of the cloud **Gemini** backend. This document
captures how it's wired and how to run it on limited hardware.

## Backends

Set `OCR_BACKEND` in `backend/.env`:

| Value      | What it is                          | Hardware                         |
|------------|-------------------------------------|----------------------------------|
| `qwen_vl`  | Local Qwen2-VL-2B handwriting VLM    | GPU strongly recommended         |
| `gemini`   | Google Gemini Vision API (cloud)     | None (no GPU) — best accuracy    |
| `nougat`   | Meta Nougat — **printed** docs only  | Poor on handwriting; avoid here  |
| `mock`     | Deterministic stub for tests/CI      | None                             |

`OCR_DEVICE=auto` (default) uses CUDA if available, otherwise CPU.

## Why a GPU matters here

Qwen2-VL-2B is ~2B params:

- **fp32:** ~8 GB weights → OOMs on a <16 GB-RAM CPU machine.
- **bf16 (CPU path):** ~4 GB weights, runs but **slow** (tens of seconds–minutes/crop).
- **fp16 (GPU):** ~4 GB weights — too big for a plain load on a 4 GB card.

On a small GPU we use **`device_map="auto"` offloading** (via `accelerate`): most
layers sit on the GPU, the overflow spills to CPU RAM. We also cap image
resolution (`max_pixels`) so the vision tower's activations don't OOM the card.

### Measured on an RTX 2050 (4 GB VRAM), CUDA 13.0
- Peak VRAM: **~3.2 GB** (a few layers offloaded to CPU)
- Model load: **~2 min** (one-time, at server start)
- Per-crop transcription: **~6–7 s**

## GPU setup (Windows, Python 3.13)

1. **NVIDIA driver** must be installed and working — verify with `nvidia-smi`
   (shows the GPU + a CUDA version). If it's missing, install from your laptop
   OEM or nvidia.com, then reboot.

2. **Install a CUDA build of torch** matching your driver's CUDA version. For
   CUDA 13.x:
   ```
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
   ```
   (Use `cu128`, `cu126`, etc. for older drivers.) Verify:
   ```
   python -c "import torch; print(torch.cuda.is_available())"   # -> True
   ```

3. **Enable local OCR** in `backend/.env`:
   ```
   OCR_BACKEND=qwen_vl
   OCR_DEVICE=auto
   ```

4. First run downloads the model (~4.5 GB) to the Hugging Face cache.

## Notes / gotchas

- **`bitsandbytes` 4-bit is NOT available** for Python 3.13 on Windows (no wheel),
  so we use offloading instead of 4-bit quantization. On Linux or Python ≤3.12
  you could `pip install bitsandbytes` and load in 4-bit (~1.2 GB VRAM) for a
  speedup — left out here for portability.
- **Handwriting accuracy:** the smoke test uses rendered text. Validate real
  accuracy on a few genuine handwritten crops; Qwen2-VL is decent but messy
  handwriting will be lower than clean print. Gemini remains the most accurate.
- **Bigger GPUs:** with ≥8 GB VRAM the model fits fully in fp16 (no offload,
  faster), and you can move up to `Qwen2-VL-7B` by setting `qwen_model_id`.
- **Startup cost:** the model loads once when the pipeline initializes and stays
  resident. Don't reinstantiate `OCRPipeline` per request.
