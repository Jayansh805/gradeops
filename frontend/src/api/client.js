// api/client.js — GradeOps API wrapper
// All paths are relative (proxied by Vite to http://localhost:8000)

const BASE = '/api/v1';

function getToken() {
  return localStorage.getItem('gradeops_token');
}

async function request(path, options = {}) {
  const headers = { ...options.headers };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }

  // Return raw response for streaming (CSV export)
  if (options._raw) return res;

  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return res.json();
  return res.text();
}

export const api = {
  /* ── Auth ─────────────────────────────── */
  login(email, password) {
    const body = new URLSearchParams({ username: email, password });
    return request('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
  },

  register(data) {
    return request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  me() {
    return request('/auth/me');
  },

  /* ── Exams ────────────────────────────── */
  submitExam(formData) {
    // formData is a FormData object — don't set Content-Type (browser sets multipart boundary)
    return request('/exams', { method: 'POST', body: formData });
  },

  /* ── Exam listing ──────────────────────── */
  listExams() {
    return request('/exams');
  },

  /* ── Jobs ─────────────────────────────── */
  getJob(jobId) {
    return request(`/jobs/${jobId}`);
  },

  /* ── Dashboard (TA) ───────────────────── */
  getDashboard(examId) {
    return request(`/exams/${examId}/dashboard`);
  },

  /* ── Grades ───────────────────────────── */
  getGrades(examId, filters = {}) {
    const params = new URLSearchParams(
      Object.fromEntries(Object.entries(filters).filter(([, v]) => v != null))
    );
    const qs = params.toString();
    return request(`/exams/${examId}/grades${qs ? `?${qs}` : ''}`);
  },

  reviewGrade(examId, payload) {
    return request(`/grades/review?exam_id=${examId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  bulkApprove(examId, payload) {
    return request(`/grades/review/bulk?exam_id=${examId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  exportGradesUrl(examId) {
    return `${BASE}/exams/${examId}/grades/export`;
  },

  /* ── Plagiarism ───────────────────────── */
  getPlagiarism(examId, minScore = 0) {
    return request(`/exams/${examId}/plagiarism?min_score=${minScore}`);
  },

  /* ── Health ───────────────────────────── */
  health() {
    return request('/health');
  },
};

export default api;
