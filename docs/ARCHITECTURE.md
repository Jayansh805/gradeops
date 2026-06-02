# GradeOps — Answer-Sheet Lifecycle & Architecture

End-to-end journey of a scanned answer sheet, from upload to verified grade,
with the component and technology used at every step. Diagrams are Mermaid
(render automatically on GitHub).

---

## 1. System overview (layers & tech)

```mermaid
flowchart TB
    subgraph CLIENT["🖥️ Frontend — React 18 + Vite + Tailwind v4"]
        direction LR
        LOGIN["Login.jsx"]
        UP["UploadExam.jsx<br/>(drag-drop PDFs + JSON rubric)"]
        EXLIST["ExamsList.jsx"]
        REVIEW["ReviewDashboard.jsx<br/>(split-screen HITL + hotkeys)"]
        PLAG["PlagiarismView.jsx"]
        CLIENTJS["api/client.js<br/>(fetch + JWT in localStorage)"]
    end

    subgraph API["⚙️ API Layer — FastAPI + Uvicorn"]
        direction LR
        AUTH["auth.py<br/>JWT (python-jose) + bcrypt/passlib<br/>RBAC: require_instructor / require_ta"]
        ROUTES["api_routes.py<br/>REST endpoints + Pydantic validation"]
        STATIC["StaticFiles mount<br/>/crops/*.png"]
    end

    subgraph WORKER["🧵 Async Worker — TaskManager (threading)"]
        direction LR
        JOB["in-memory Job store<br/>queued→running→completed/failed"]
        PIPE["GradeOpsPipeline.run_exam()<br/>orchestrates 4 stages"]
    end

    subgraph AIML["🧠 AI / ML Pipeline"]
        direction LR
        OCR["OCR — ocr_pipeline.py<br/>PyMuPDF crop → Qwen2-VL-2B<br/>(torch+CUDA / accelerate)"]
        GRADE["Grading — grading_agent.py<br/>LangGraph state machine<br/>→ Groq Llama-3.3-70b"]
        PL["Plagiarism — plagiarism_detector.py<br/>scikit-learn TF-IDF + cosine"]
    end

    subgraph DATA["💾 Persistence"]
        direction LR
        PG[("PostgreSQL<br/>users / auth<br/>SQLAlchemy async + asyncpg")]
        STORE[("Storage backend<br/>local JSON: ocr.json / grades.json<br/>+ ./crops  •OR•  S3 + DynamoDB")]
    end

    subgraph EXT["☁️ External (optional fallbacks)"]
        GEM["Gemini Vision API<br/>(OCR fallback)"]
        GROQ["Groq Cloud LPU<br/>(grading LLM)"]
    end

    CLIENT <-->|"HTTPS /api/v1<br/>Vite proxy :5173→:8000"| API
    AUTH <--> PG
    ROUTES --> WORKER
    PIPE --> AIML
    AIML --> STORE
    REVIEW -.->|"GET /crops/*"| STATIC
    GRADE --> GROQ
    OCR -.fallback.-> GEM
    ROUTES <--> STORE
```

---

## 2. The answer-sheet lifecycle (upload → verified)

```mermaid
flowchart TD
    A0["👤 Instructor logs in<br/><i>Login.jsx → POST /api/v1/auth/login</i><br/>form-urlencoded; bcrypt verify; JWT returned"] --> A1

    A1["📤 Upload bulk PDFs + JSON rubric<br/><i>UploadExam.jsx → FormData → POST /api/v1/exams</i><br/>multipart; Bearer JWT; require_instructor"] --> A2

    A2["🆔 submit_exam()<br/>save PDFs to tempdir • parse rubric →<br/>ExamBatch (Pydantic) • exam_id = uuid4"] --> A3

    A3["🧵 TaskManager.submit() → background thread<br/><b>returns instantly</b>: {exam_id, job_id, status: queued}"] --> POLL & B1

    POLL["🔄 Frontend polls<br/>GET /api/v1/jobs/{job_id}<br/>queued → running → completed"]

    subgraph BG["GradeOpsPipeline.run_exam() — runs in worker thread"]
        direction TB
        B1["[1/4] 📄 OCR<br/>PyMuPDF renders PDF→images @200 DPI<br/>_extract_question_crop (auto-split / regions)<br/>save crop PNG → ./crops"] --> B2

        B2["🔤 Transcribe each crop<br/><b>Qwen2-VL-2B</b> on GPU (device_map=auto)<br/>→ raw_text + confidence<br/>→ OCRResult → save_ocr_bulk (ocr.json)"] --> B3

        B3["[2/4] 🧠 Grade — LangGraph loop<br/>per criterion: LLM (Groq Llama-3.3-70b)<br/>→ {awarded, justification}; partial credit<br/>→ aggregate → GradeResult (status=AI_GRADED)"] --> B4

        B4["[3/4] 🕵️ Plagiarism<br/>scikit-learn TF-IDF + cosine across answers<br/>pairs ≥ 0.82 → mark grade FLAGGED"] --> B5

        B5["[4/4] 💾 Persist grades<br/>save_grades_bulk → grades.json<br/>job → completed"]
    end

    B5 --> C1

    C1["👤 TA logs in → opens review<br/><i>ReviewDashboard.jsx → GET /exams/{id}/dashboard</i><br/>returns pending (AI_GRADED/FLAGGED) + crop URLs"] --> C2

    C2["👀 Split-screen verify (HITL)<br/>cropped image (/crops/*) ‖ transcription + score + justification<br/>plagiarism bar if flagged"] --> C3

    C3{"⌨️ TA decision<br/>(keyboard shortcuts)"}
    C3 -->|"A = approve"| C4A["POST /grades/review<br/>status → APPROVED"]
    C3 -->|"O = override score"| C4B["POST /grades/review<br/>status → OVERRIDDEN + ta note"]
    C3 -->|"↑/↓ navigate"| C2

    C4A --> D1
    C4B --> D1

    D1["💾 apply_ta_review() → update_grade()<br/>persisted to grades.json"] --> D2
    D2["📊 Instructor: ExamsList + CSV export<br/>GET /exams/{id}/grades/export (csv module)"]
```

---

## 3. Step-by-step: component + technology at each step

| # | Step | Frontend | Backend / Endpoint | Technology |
|---|------|----------|--------------------|------------|
| 1 | **Login** | `Login.jsx`, `AuthContext` | `POST /api/v1/auth/login` | JWT (python-jose), bcrypt+passlib, PostgreSQL (SQLAlchemy async / asyncpg) |
| 2 | **Upload sheets + rubric** | `UploadExam.jsx` (drag-drop, `FormData`) | `POST /api/v1/exams` (`require_instructor`) | FastAPI `UploadFile` + python-multipart; Pydantic `ExamBatch`/`Rubric` |
| 3 | **Queue job** | — (gets `job_id`) | `TaskManager.submit()` | Python `threading`, in-memory Job store, `uuid4` |
| 4 | **PDF → crops** | — | `OCRPipeline.process_exam_pdf` | **PyMuPDF (fitz)** @200 DPI, Pillow, auto-split/regions → PNG in `./crops` |
| 5 | **Transcribe handwriting** | — | `_QwenVLBackend.transcribe` | **Qwen2-VL-2B** (transformers, torch+CUDA cu130, accelerate `device_map=auto`); fallbacks: Gemini Vision / Nougat / mock |
| 6 | **Store OCR** | — | `storage.save_ocr_bulk` | local `ocr.json` (+ crops on disk) **or** S3 + DynamoDB (boto3) |
| 7 | **Grade vs rubric** | — | `GradingAgent.grade_batch` | **LangGraph** state machine (grade_criterion → aggregate), **LangChain + Groq** Llama-3.3-70b; partial credit + JSON justifications |
| 8 | **Plagiarism scan** | — | `PlagiarismDetector.full_report` | **scikit-learn** TF-IDF + cosine similarity; threshold 0.82 (sentence-transformers optional) |
| 9 | **Persist grades** | — | `storage.save_grades_bulk` | local `grades.json` **or** DynamoDB |
| 10 | **Poll status** | `client.getJob()` | `GET /api/v1/jobs/{job_id}` | polling; status enum queued→running→completed |
| 11 | **TA review feed** | `ReviewDashboard.jsx` | `GET /api/v1/exams/{id}/dashboard` | returns pending grades + `/crops/*` URLs (`require_ta_or_above`) |
| 12 | **View crop side-by-side** | `<img src="/crops/...">` | FastAPI `StaticFiles` mount `/crops` | static file serving |
| 13 | **Approve / Override** | hotkeys `A`/`O`/`↑↓` | `POST /api/v1/grades/review` | `apply_ta_review` → status APPROVED / OVERRIDDEN |
| 14 | **Export** | `ExamsList.jsx` | `GET /api/v1/exams/{id}/grades/export` | Python `csv` → CSV download |

---

## 4. HITL request/response timing (sequence)

```mermaid
sequenceDiagram
    participant I as Instructor (React)
    participant API as FastAPI
    participant W as Worker thread
    participant ML as OCR+Grade+Plag
    participant DB as Storage
    participant T as TA (React)

    I->>API: POST /exams (PDFs + rubric, JWT)
    API->>W: submit(run_exam)
    API-->>I: 200 {exam_id, job_id, queued}
    Note over W,ML: runs async (first OCR call loads<br/>Qwen2-VL ~2 min once, then ~6-7s/crop)
    W->>ML: [1] PyMuPDF crop → Qwen2-VL OCR
    W->>ML: [2] LangGraph → Groq grading
    W->>ML: [3] scikit-learn plagiarism
    W->>DB: [4] save ocr.json + grades.json
    loop until done
        I->>API: GET /jobs/{job_id}
        API-->>I: status (running→completed)
    end
    T->>API: GET /exams/{id}/dashboard (JWT, TA)
    API-->>T: pending grades + crop URLs
    T->>API: POST /grades/review (A=approve / O=override)
    API->>DB: update_grade → APPROVED/OVERRIDDEN
    API-->>T: updated grade
```

---

## 5. Key design notes

- **Non-blocking upload:** `POST /exams` returns a `job_id` immediately; heavy
  OCR/grading runs in a background thread (`TaskManager`). Production target:
  swap for **Celery + Redis** (noted in `background_tasks.py`).
- **Model residency:** the OCR pipeline is a lazy singleton (`get_pipeline()`),
  so Qwen2-VL loads **once** into VRAM on the first OCR request, then stays warm.
- **Pluggable backends:** OCR (`qwen_vl`/`gemini`/`nougat`/`mock`), LLM
  (`groq`/`gemini`/`openai`/`anthropic`/`together`), and storage (`local`/`s3`)
  are all swappable via `.env` with no code change.
- **RBAC boundary:** instructors upload/export; TAs review/verify — enforced by
  FastAPI dependencies (`require_instructor`, `require_ta_or_above`).
```
