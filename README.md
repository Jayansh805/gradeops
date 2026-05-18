# ⚡ GradeOps — AI Exam Grading Pipeline

Full-stack HITL (Human-in-the-Loop) grading system:
- **Backend**: FastAPI + PostgreSQL + SQLAlchemy (async)
- **Frontend**: React + Vite (dark, keyboard-driven TA dashboard)
- **AI**: OCR → LLM grading → Plagiarism detection pipeline

---

## 🚀 Quick Start — Docker (Recommended)

```bash
# 1. Clone / unzip the project
cd gradeops_full

# 2. Run everything (Postgres + FastAPI + React)
docker compose up --build

# Wait ~60s for build to finish, then open:
# Frontend:  http://localhost:5173
# API docs:  http://localhost:8000/docs
```

**Demo accounts (auto-seeded):**
| Role       | Email                       | Password      |
|------------|-----------------------------|---------------|
| Instructor | instructor@gradeops.dev     | instructor123 |
| TA         | ta@gradeops.dev             | ta123         |

---

## 🛠 Local Dev (No Docker)

### Backend

```bash
cd backend

# 1. Create & activate venv
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment
cp .env.example .env
# Edit .env → set DATABASE_URL to your Postgres instance

# 4. Run Postgres (quick with Docker)
docker run -d \
  -e POSTGRES_USER=gradeops \
  -e POSTGRES_PASSWORD=gradeops \
  -e POSTGRES_DB=gradeops \
  -p 5432:5432 postgres:16-alpine

# 5. Start FastAPI (tables auto-created on first run)
uvicorn main:app --reload --port 8000

# API docs → http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev

# Opens → http://localhost:5173
# API calls are proxied to http://localhost:8000 via vite.config.js
```

---

## 📁 Folder Structure

```
gradeops_full/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── auth.py              # JWT auth + RBAC (PostgreSQL-backed)
│   ├── database.py          # SQLAlchemy async engine + UserORM
│   ├── config.py            # Pydantic settings (reads .env)
│   ├── models.py            # Pydantic data schemas
│   ├── api_routes.py        # REST endpoints
│   ├── pipeline.py          # OCR → Grade → Plagiarism orchestrator
│   ├── ocr_pipeline.py      # OCR (Qwen-VL / Nougat / mock)
│   ├── grading_agent.py     # LLM grading agent (LangGraph)
│   ├── plagiarism_detector.py
│   ├── storage.py           # Local / S3 storage backends
│   ├── background_tasks.py  # Thread-based job queue
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── api/client.js         # API wrapper (all endpoints)
│   │   ├── context/AuthContext.jsx
│   │   ├── components/
│   │   │   ├── Layout.jsx         # Sidebar navigation
│   │   │   └── ProtectedRoute.jsx
│   │   └── pages/
│   │       ├── Login.jsx
│   │       ├── Register.jsx
│   │       ├── instructor/
│   │       │   ├── UploadExam.jsx  # Drag & drop + rubric editor
│   │       │   └── ExamsList.jsx   # Results + CSV export
│   │       └── ta/
│   │           ├── ReviewDashboard.jsx  # Keyboard shortcuts
│   │           └── PlagiarismView.jsx
│   ├── vite.config.js       # Proxy /api → backend:8000
│   ├── nginx.conf           # Production SPA + proxy config
│   └── Dockerfile
│
├── docker-compose.yml
└── README.md
```

---

## 🔑 Key Features

### Instructor Portal
- **Upload Exam**: Drag & drop student PDFs + JSON rubric editor with template
- **Exam Results**: Stats dashboard, grade table, CSV export
- **Job Tracking**: Real-time polling of AI pipeline status

### TA Dashboard
- **Keyboard shortcuts**: `A` = approve, `O` = override, `↑↓` = navigate
- **Bulk approve**: approve all pending grades at once
- **Override modal**: set new score + justification note
- **Progress bar**: tracks % of grades reviewed

### Plagiarism View
- Per-exam similarity scan with threshold filter
- Visual similarity bars (red > 90%, amber > 75%)

---

## ⚙️ Environment Variables (`.env`)

```env
# Database (required)
DATABASE_URL=postgresql+asyncpg://gradeops:gradeops@localhost:5432/gradeops

# JWT
JWT_SECRET=change_me_to_random_32_char_string
JWT_EXPIRE_HOURS=24

# AI backends
OCR_BACKEND=mock       # mock | qwen_vl | nougat
LLM_PROVIDER=mock      # mock | openai | anthropic | together
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# Storage
STORAGE_BACKEND=local  # local | s3
STORAGE_DATA_DIR=./gradeops_data
```

---

## 📮 API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/auth/login` | — | Login → JWT |
| POST | `/api/v1/auth/register` | — | Register TA |
| GET | `/api/v1/auth/me` | Any | Profile |
| POST | `/api/v1/exams` | Instructor | Submit exam PDFs |
| GET | `/api/v1/jobs/{id}` | TA+ | Poll job status |
| GET | `/api/v1/exams/{id}/dashboard` | TA+ | Review queue |
| GET | `/api/v1/exams/{id}/grades` | TA+ | All grades |
| GET | `/api/v1/exams/{id}/grades/export` | Instructor | CSV download |
| POST | `/api/v1/grades/review` | TA+ | Approve/Override |
| POST | `/api/v1/grades/review/bulk` | TA+ | Bulk approve |
| GET | `/api/v1/exams/{id}/plagiarism` | TA+ | Plagiarism flags |

Full interactive docs: **http://localhost:8000/docs**
