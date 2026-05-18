import { useState, useEffect } from 'react';
import api from '../../api/client';
import './ExamsList.css';

export default function ExamsList() {
  const [examId,    setExamId]    = useState('');
  const [grades,    setGrades]    = useState(null);
  const [plag,      setPlag]      = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState('');
  const [tab,       setTab]       = useState('grades');
  const [examsList, setExamsList] = useState([]);
  const [listLoading, setListLoading] = useState(true);

  /* ── Auto-load exam list on mount ── */
  useEffect(() => {
    api.listExams()
      .then(data => setExamsList(data.exams || []))
      .catch(() => setExamsList([]))
      .finally(() => setListLoading(false));
  }, []);

  async function loadExam(id) {
    const target = (id ?? examId).trim();
    if (!target) { setError('Enter an Exam ID.'); return; }
    setError(''); setLoading(true); setGrades(null); setPlag(null); setExamId(target);
    try {
      const [g, p] = await Promise.all([
        api.getGrades(target),
        api.getPlagiarism(target),
      ]);
      setGrades(g);
      setPlag(p);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const stats = grades ? {
    total: grades.length,
    approved: grades.filter(g => g.status === 'approved').length,
    pending: grades.filter(g => ['ai_graded','pending'].includes(g.status)).length,
    flagged: grades.filter(g => g.status === 'flagged' || g.plagiarism_flag).length,
    avgScore: grades.length
      ? (grades.reduce((s, g) => s + g.total_awarded, 0) / grades.length).toFixed(1)
      : 0,
  } : null;

  return (
    <div className="animate-in">
      <div className="page-header">
        <h1>Exam Results</h1>
        <p>Select an exam from the list below, or paste an ID directly.</p>
      </div>

      {/* Exam list */}
      {listLoading ? (
        <div className="card mb-4"><span className="spinner" /> Loading exams…</div>
      ) : examsList.length > 0 ? (
        <div className="card mb-4">
          <h3 style={{ marginBottom: 12 }}>My Exams</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Exam ID</th><th>Course</th><th>Students</th><th>Status</th><th></th></tr>
              </thead>
              <tbody>
                {examsList.map(ex => (
                  <tr key={ex.exam_id}>
                    <td className="mono" style={{ fontSize: 12 }}>{ex.exam_id}</td>
                    <td>{ex.course_id || '—'}</td>
                    <td>{ex.student_count}</td>
                    <td><span className={`badge badge-${ex.processed ? 'approved' : 'pending'}`}>
                      {ex.processed ? 'processed' : 'pending'}
                    </span></td>
                    <td>
                      <button className="btn btn-ghost btn-sm"
                        onClick={() => loadExam(ex.exam_id)}>
                        Load
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {/* Exam lookup */}
      <div className="card">
        <div className="lookup-row">
          <input
            type="text"
            className="form-input"
            placeholder="Paste Exam ID (UUID)"
            value={examId}
            onChange={e => setExamId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadExam()}
          />
          <button className="btn btn-primary" onClick={() => loadExam()} disabled={loading}>
            {loading ? <span className="spinner" /> : 'Load'}
          </button>
          {grades && (
            <a
              href={api.exportGradesUrl(examId.trim())}
              target="_blank"
              rel="noreferrer"
              className="btn btn-ghost"
            >
              ⬇ Export CSV
            </a>
          )}
        </div>
        {error && <div className="alert alert-error mt-4">{error}</div>}
      </div>

      {/* Stats */}
      {stats && (
        <>
          <div className="stats-grid mt-6">
            <StatCard label="Total Grades" value={stats.total} />
            <StatCard label="Avg Score"    value={stats.avgScore} gold />
            <StatCard label="Approved"     value={stats.approved} color="success" />
            <StatCard label="Pending Review" value={stats.pending} color="warning" />
            <StatCard label="Flagged"      value={stats.flagged}  color="danger" />
          </div>

          {/* Tabs */}
          <div className="tabs mt-6">
            {['grades','plagiarism'].map(t => (
              <button
                key={t}
                className={`tab ${tab === t ? 'tab--active' : ''}`}
                onClick={() => setTab(t)}
              >
                {t === 'grades' ? `📊 Grades (${grades.length})` : `🔍 Plagiarism (${plag?.flagged_count ?? 0})`}
              </button>
            ))}
          </div>

          {tab === 'grades' && <GradesTable grades={grades} />}
          {tab === 'plagiarism' && <PlagTable data={plag} />}
        </>
      )}

      {!grades && !loading && (
        <div className="empty-state mt-6">
          <div className="icon">📋</div>
          <h3>No exam loaded</h3>
          <p>Enter an exam ID above to view results and export grades.</p>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, gold, color }) {
  const cls = gold ? 'text-gold' : color ? `text-${color}` : 'text-gold';
  return (
    <div className="card card-sm stat-card">
      <div className={`stat-val ${cls}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function GradesTable({ grades }) {
  if (!grades.length) return <div className="empty-state mt-4"><p>No grades found.</p></div>;
  return (
    <div className="card mt-4 table-wrap">
      <table>
        <thead>
          <tr>
            <th>Student</th><th>Q#</th><th>Score</th><th>Possible</th>
            <th>%</th><th>Status</th><th>Plagiarism</th>
          </tr>
        </thead>
        <tbody>
          {grades.map(g => (
            <tr key={g.grade_id}>
              <td className="mono">{g.student_id}</td>
              <td className="mono">{g.question_number}</td>
              <td className="mono text-gold">{g.total_awarded}</td>
              <td className="mono text-dim">{g.total_possible}</td>
              <td className="mono">{((g.total_awarded / g.total_possible) * 100).toFixed(0)}%</td>
              <td><span className={`badge badge-${g.status}`}>{g.status}</span></td>
              <td>{g.plagiarism_flag
                ? <span className="badge badge-flagged">⚠ {(g.plagiarism_similarity * 100).toFixed(0)}%</span>
                : <span className="text-mute">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlagTable({ data }) {
  if (!data || data.flagged_count === 0)
    return <div className="empty-state mt-4"><div className="icon">✅</div><p>No plagiarism flagged.</p></div>;
  return (
    <div className="card mt-4 table-wrap">
      <table>
        <thead>
          <tr><th>Student A</th><th>Student B</th><th>Q#</th><th>Similarity</th><th>Phrases</th></tr>
        </thead>
        <tbody>
          {data.results.map((r, i) => (
            <tr key={i}>
              <td className="mono">{r.student_id}</td>
              <td className="mono text-dim">—</td>
              <td className="mono">{r.question_number}</td>
              <td><span className="badge badge-flagged">{(r.plagiarism_similarity * 100).toFixed(0)}%</span></td>
              <td className="text-dim text-sm">—</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
