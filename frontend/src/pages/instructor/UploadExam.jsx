import { useState, useRef, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import './UploadExam.css';

const RUBRIC_TEMPLATE = JSON.stringify([
  {
    question_number: 1,
    total_points: 10,
    strict_mode: false,
    criteria: [
      {
        criterion_id: "c1_q1",
        description: "Correct algorithm / approach",
        max_points: 5,
        required_keywords: [],
        partial_credit: true
      },
      {
        criterion_id: "c2_q1",
        description: "Proper explanation / justification",
        max_points: 3,
        required_keywords: [],
        partial_credit: true
      },
      {
        criterion_id: "c3_q1",
        description: "Correct final answer",
        max_points: 2,
        required_keywords: [],
        partial_credit: false
      }
    ]
  }
], null, 2);

export default function UploadExam() {
  const { user } = useAuth();

  const [courseId,    setCourseId]    = useState('');
  const [rubricJson,  setRubricJson]  = useState(RUBRIC_TEMPLATE);
  const [pdfFiles,    setPdfFiles]    = useState([]);
  const [dragging,    setDragging]    = useState(false);
  const [submitting,  setSubmitting]  = useState(false);
  const [job,         setJob]         = useState(null);
  const [polling,     setPolling]     = useState(false);
  const [error,       setError]       = useState('');
  const [jsonError,   setJsonError]   = useState('');

  const dropRef    = useRef();
  const pollTimer  = useRef(null);

  /* ── Drag-and-drop ── */
  const onDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false);
    const files = Array.from(e.dataTransfer.files).filter(f => f.type === 'application/pdf');
    setPdfFiles(prev => {
      const existing = new Set(prev.map(f => f.name));
      return [...prev, ...files.filter(f => !existing.has(f.name))];
    });
  }, []);

  function onFileInput(e) {
    const files = Array.from(e.target.files);
    setPdfFiles(prev => {
      const existing = new Set(prev.map(f => f.name));
      return [...prev, ...files.filter(f => !existing.has(f.name))];
    });
  }

  function removeFile(name) {
    setPdfFiles(prev => prev.filter(f => f.name !== name));
  }

  /* ── JSON validation ── */
  function validateJson(val) {
    try { JSON.parse(val); setJsonError(''); return true; }
    catch (e) { setJsonError(e.message); return false; }
  }

  /* ── Poll job ── */
  function startPolling(jobId) {
    setPolling(true);
    pollTimer.current = setInterval(async () => {
      try {
        const j = await api.getJob(jobId);
        setJob(j);
        if (j.status === 'completed' || j.status === 'failed') {
          clearInterval(pollTimer.current);
          setPolling(false);
        }
      } catch { clearInterval(pollTimer.current); setPolling(false); }
    }, 2000);
  }

  /* ── Submit ── */
  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (pdfFiles.length === 0) { setError('Upload at least one student PDF.'); return; }
    if (!validateJson(rubricJson)) { setError('Fix the rubric JSON errors.'); return; }

    const fd = new FormData();
    fd.append('course_id',    courseId.trim() || 'COURSE-001');
    // instructor_id is resolved server-side from the auth token
    fd.append('rubrics_json',  rubricJson);
    pdfFiles.forEach(f => fd.append('pdfs', f));

    setSubmitting(true);
    try {
      const result = await api.submitExam(fd);
      setJob({ job_id: result.job_id, exam_id: result.exam_id, status: result.status });
      startPolling(result.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    clearInterval(pollTimer.current);
    setJob(null); setPdfFiles([]); setCourseId(''); setError(''); setPolling(false);
  }

  /* ── Render ── */
  return (
    <div className="animate-in">
      <div className="page-header">
        <h1>Upload Exam</h1>
        <p>Submit scanned student PDFs and a grading rubric for AI processing.</p>
      </div>

      {job ? (
        <JobStatus job={job} polling={polling} onReset={reset} />
      ) : (
        <form onSubmit={handleSubmit} className="upload-form">
          {/* Course ID */}
          <div className="card">
            <h3 className="card-title">Exam Details</h3>
            <div className="form-group mt-4">
              <label className="form-label">Course ID</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. CS301-2024-FALL"
                value={courseId}
                onChange={e => setCourseId(e.target.value)}
              />
            </div>
          </div>

          {/* PDF upload */}
          <div className="card mt-4">
            <h3 className="card-title">Student PDFs</h3>
            <p className="text-dim text-sm mt-1" style={{marginBottom:'16px'}}>
              Each filename is used as the student ID — name them <code>studentID.pdf</code>
            </p>

            <div
              ref={dropRef}
              className={`drop-zone ${dragging ? 'drop-zone--active' : ''}`}
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => document.getElementById('pdf-input').click()}
            >
              <div className="drop-zone-icon">📂</div>
              <p>Drop PDF files here or <span className="text-gold">click to browse</span></p>
              <p className="text-sm text-mute">Multiple PDFs accepted</p>
              <input id="pdf-input" type="file" accept=".pdf" multiple hidden onChange={onFileInput} />
            </div>

            {pdfFiles.length > 0 && (
              <div className="pdf-list mt-4">
                {pdfFiles.map(f => (
                  <div key={f.name} className="pdf-item">
                    <span>📄</span>
                    <span className="pdf-name">{f.name}</span>
                    <span className="pdf-size">{(f.size / 1024).toFixed(0)} KB</span>
                    <button type="button" className="btn btn-icon btn-danger btn-sm"
                      onClick={() => removeFile(f.name)}>✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Rubric JSON */}
          <div className="card mt-4">
            <div className="flex justify-between items-center">
              <h3 className="card-title">Grading Rubric (JSON)</h3>
              <button type="button" className="btn btn-ghost btn-sm"
                onClick={() => { setRubricJson(RUBRIC_TEMPLATE); setJsonError(''); }}>
                Reset Template
              </button>
            </div>
            <p className="text-dim text-sm mt-1" style={{marginBottom:'12px'}}>
              Define criteria, max points, and required keywords per question.
            </p>
            <textarea
              className="form-textarea"
              style={{ minHeight: '280px' }}
              value={rubricJson}
              onChange={e => { setRubricJson(e.target.value); validateJson(e.target.value); }}
              spellCheck={false}
            />
            {jsonError && (
              <p className="text-danger text-sm mt-1">⚠ JSON error: {jsonError}</p>
            )}
          </div>

          {error && <div className="alert alert-error mt-4">{error}</div>}

          <div className="upload-actions mt-4">
            <button type="submit" className="btn btn-primary btn-lg" disabled={submitting}>
              {submitting
                ? <><span className="spinner" /> Submitting…</>
                : <> Submit for Grading ({pdfFiles.length} PDF{pdfFiles.length !== 1 ? 's' : ''})</>
              }
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function JobStatus({ job, polling, onReset }) {
  return (
    <div className="card animate-in job-status-card">
      <div className="job-status-header">
        <div>
          <h2>Processing Exam</h2>
          <p className="text-dim text-sm mt-1">exam: <code>{job.exam_id}</code></p>
        </div>
        <span className={`badge badge-${job.status}`}>{job.status}</span>
      </div>

      <div className="job-timeline">
        {['queued', 'running', 'completed'].map((step, i) => {
          const statuses = ['queued', 'running', 'completed', 'failed'];
          const curIdx = statuses.indexOf(job.status);
          const stepIdx = statuses.indexOf(step);
          const done = curIdx > stepIdx;
          const active = curIdx === stepIdx;
          const failed = job.status === 'failed' && step === 'completed';

          return (
            <div key={step} className={`timeline-step ${done ? 'done' : ''} ${active ? 'active' : ''} ${failed ? 'failed' : ''}`}>
              <div className="step-dot">
                {done ? '✓' : active && !failed ? <span className="animate-pulse">●</span> : failed ? '✕' : ''}
              </div>
              <div className="step-label">{step.toUpperCase()}</div>
            </div>
          );
        })}
      </div>

      {polling && (
        <div className="alert alert-info mt-4">
          <span className="spinner" style={{marginRight:8}} /> AI OCR + Grading pipeline running… polling every 2s
        </div>
      )}

      {job.status === 'completed' && job.result_summary && (
        <div className="result-summary mt-4">
          <h4>Results</h4>
          <div className="summary-grid mt-2">
            {Object.entries(job.result_summary).map(([k, v]) => (
              <div key={k} className="summary-item">
                <span className="summary-key">{k.replace(/_/g, ' ')}</span>
                <span className="summary-val mono">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {job.status === 'failed' && (
        <div className="alert alert-error mt-4">Pipeline error: {job.error}</div>
      )}

      <div className="flex gap-3 mt-6">
        <button className="btn btn-primary" onClick={onReset}>Upload Another Exam</button>
        {job.status === 'completed' && (
          <a href={`/ta/review?exam=${job.exam_id}`} className="btn btn-ghost">
            → Review Grades
          </a>
        )}
      </div>
    </div>
  );
}
