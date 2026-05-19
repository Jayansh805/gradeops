Here is the merged and refined `README.md`. It combines the high-level project overviews, the detailed Docker and local setup instructions, the folder structure, and the API endpoints into a single, professional document.

I also updated the AI configuration sections to reflect your final implementation architecture (Gemini for OCR, Groq for the LangGraph logic layer).

---

# ⚡ GradeOps 🎓 — AI-Powered Exam Grading Pipeline

**GradeOps** is a full-stack, Human-in-the-Loop (HITL) grading system designed to process, transcribe, and evaluate scanned handwritten student exams at scale.

It combines a robust asynchronous Python backend for Optical Character Recognition (OCR) and Agentic LLM evaluation with a sleek, keyboard-driven React dashboard. This allows Teaching Assistants (TAs) to rapidly review, override, and distribute AI-proposed grades while saving massive amounts of administrative time.

### 🛠 Tech Stack

* **Backend:** Python 3.10+, FastAPI, PostgreSQL + SQLAlchemy (async), Uvicorn
* **Frontend:** React 18, Vite, Tailwind CSS v4, React Router
* **AI/ML Pipeline:** LangChain, LangGraph, PyMuPDF, scikit-learn (plagiarism vector math)
* **AI Models:** Gemini 2.5 Flash Lite (Vision/OCR), Groq / Llama-3.3-70b-versatile (Grading Logic)

---

## 🔑 Key Features

* **Intelligent AI Pipeline:** Extracts text from messy handwritten PDFs using Gemini, then evaluates the answers against strict JSON rubrics using Groq's high-speed LPU inference.
* **Instructor Portal:** Drag-and-drop exam uploads, a JSON rubric editor with templates, and a stats dashboard with one-click CSV grade exports.
* **TA Review Dashboard (HITL):** A split-screen, dark-mode interface optimized for speed. TAs can visually verify OCR results and use keyboard shortcuts (`A` to approve, `O` to override, `↑↓` to navigate) to finalize grades.
* **Semantic Plagiarism Detection:** Submissions are automatically embedded and checked against each other. Highly similar semantic structures are flagged with visual similarity bars (Red > 90%, Amber > 75%).
* **Extensible Storage:** Run fully locally (local file system) or seamlessly scale to AWS (S3 for PDFs/images).

---

## 🚀 Quick Start — Docker (Recommended)

The easiest way to run the entire stack (Postgres + FastAPI + React) is via Docker.

```bash
# 1. Clone the repository and navigate into it
git clone <your-repo-url>
cd gradeops_full

# 2. Run everything
docker compose up --build

```

Wait ~60 seconds for the build to finish, then open:

* **Frontend Dashboard:** http://localhost:5173
* **Interactive API Docs:** http://localhost:8000/docs

**Demo accounts (auto-seeded on startup):**

| Role | Email | Password |
| --- | --- | --- |
| **Instructor** | `instructor@gradeops.dev` | `instructor123` |
| **TA** | `ta@gradeops.dev` | `ta123` |

---

## 💻 Local Development Setup (No Docker)

If you prefer to run the services manually for development, follow these steps.

### 1. Backend Setup

```bash
cd backend

# Create & activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # On Windows use: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env

```

*(Ensure you edit your `.env` to include your Groq and Gemini API keys, and your local Postgres connection string. See Configuration section below).*

**Run a local Postgres instance (quick method via Docker):**

```bash
docker run -d \
  -e POSTGRES_USER=gradeops \
  -e POSTGRES_PASSWORD=gradeops \
  -e POSTGRES_DB=gradeops \
  -p 5432:5432 postgres:16-alpine

```

**Start the FastAPI server:**
*(Database tables and demo users are auto-created on the first run).*

```bash
uvicorn main:app --reload --port 8000

```

### 2. Frontend Setup

Open a new terminal and navigate to the frontend directory:

```bash
cd frontend

# Install packages
npm install

# Run the Vite development server
npm run dev

```

Open your browser and go to `http://localhost:5173`. *(API calls are automatically proxied to `http://localhost:8000` via `vite.config.js`)*.

---

## ⚙️ Configuration (.env)

GradeOps is highly configurable. Edit your backend `.env` file to set up your specific AI and database providers:

```env
# Database (required)
DATABASE_URL=postgresql+asyncpg://gradeops:gradeops@localhost:5432/gradeops

# Security / JWT
JWT_SECRET=change_me_to_random_32_char_string
JWT_EXPIRE_HOURS=24

# AI Backends
OCR_BACKEND=gemini       
GEMINI_OCR_MODEL=gemini-2.5-flash-lite
GEMINI_API_KEY=your_gemini_key_here

LLM_PROVIDER=groq      
LLM_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=your_groq_key_here

# Storage
STORAGE_BACKEND=local  # Switch to 's3' for production
STORAGE_DATA_DIR=./gradeops_data

```

---

## 🎯 Usage Workflow

1. **Upload Exam:** The Instructor logs in, pastes a JSON grading rubric, and uploads multiple student PDF submissions via the drag-and-drop portal.
2. **Background Processing:** The FastAPI backend schedules background tasks to crop questions, run the Gemini OCR engine, and pass the text to LangGraph/Groq for rubric evaluation. Plagiarism vectors are also calculated.
3. **Review:** The TA logs in and opens the Review Dashboard. They use keyboard shortcuts to rapidly accept the AI's grade or manually override it and provide customized justification notes.
4. **Grades Overview:** Instructors view all completed assessments, check for plagiarism flags, and download the final grades in CSV format for LMS integration.

---

## 📁 Folder Structure

```text
gradeops_full/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── auth.py              # JWT auth + RBAC (PostgreSQL-backed)
│   ├── database.py          # SQLAlchemy async engine + UserORM
│   ├── config.py            # Pydantic settings (reads .env)
│   ├── models.py            # Pydantic data schemas
│   ├── api_routes.py        # REST endpoints
│   ├── pipeline.py          # OCR → Grade → Plagiarism orchestrator
│   ├── ocr_pipeline.py      # OCR (Gemini Vision integration)
│   ├── grading_agent.py     # LLM grading agent (LangGraph + Groq)
│   ├── plagiarism_detector.py # scikit-learn cosine similarity
│   ├── storage.py           # Local / S3 storage backends
│   ├── background_tasks.py  # Thread-based job queue
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── api/client.js         # API wrapper 
│   │   ├── context/AuthContext.jsx
│   │   ├── components/
│   │   │   ├── Layout.jsx        # Sidebar navigation
│   │   │   └── ProtectedRoute.jsx
│   │   └── pages/
│   │       ├── Login.jsx
│   │       ├── instructor/
│   │       │   ├── UploadExam.jsx  
│   │       │   └── ExamsList.jsx   
│   │       └── ta/
│   │           ├── ReviewDashboard.jsx  # HITL Dashboard
│   │           └── PlagiarismView.jsx
│   ├── vite.config.js       # Proxy config
│   └── Dockerfile
│
├── docker-compose.yml
└── README.md

```

---

## 📮 Core API Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| **POST** | `/api/v1/auth/login` | — | Login → Receive JWT |
| **POST** | `/api/v1/exams` | Instructor | Submit exam PDFs and JSON rubric |
| **GET** | `/api/v1/jobs/{id}` | TA+ | Poll AI background job status |
| **GET** | `/api/v1/exams/{id}/dashboard` | TA+ | Load Review Queue (HITL) |
| **POST** | `/api/v1/grades/review` | TA+ | Approve/Override an individual grade |
| **POST** | `/api/v1/grades/review/bulk` | TA+ | Bulk approve all pending AI grades |
| **GET** | `/api/v1/exams/{id}/plagiarism` | TA+ | Retrieve flagged semantic similarity pairs |
| **GET** | `/api/v1/exams/{id}/grades/export` | Instructor | Download CSV of finalized grades |