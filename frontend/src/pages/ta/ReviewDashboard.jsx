import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../api/client';
import './ReviewDashboard.css';

export default function ReviewDashboard() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const initialExam = searchParams.get('exam') || '';

  const [examId,   setExamId]   = useState(initialExam);
  const [input,    setInput]    = useState(initialExam);
  const [items,    setItems]    = useState([]);
  const [cursor,   setCursor]   = useState(0);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');
  const [stats,    setStats]    = useState(null);
  const [override, setOverride] = useState({ open: false, score: '', note: '' });
  const [toast,    setToast]    = useState('');
  const toastTimer = useRef(null);

  /* ── Load dashboard ── */
  const loadDashboard = useCallback(async (id) => {
    if (!id?.trim()) return;
    setLoading(true); setError(''); setItems([]); setCursor(0);
    try {
      const data = await api.getDashboard(id.trim());
      setItems(data.items || []);
      setStats({ total: data.total_grades, pending: data.pending });
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (initialExam) loadDashboard(initialExam); }, []);

  /* ── Toast helper ── */
  function showToast(msg) {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 2200);
  }

  /* ── Review action ── */
  const current = items[cursor];

  const doReview = useCallback(async (action, overrideScore = null, note = '') => {
    if (!current) return;
    const payload = {
      grade_id: current.grade.grade_id,
      ta_id:    user.user_id,
      action,
      ...(action === 'override' ? { override_score: parseFloat(overrideScore), override_note: note } : {}),
    };
    try {
      await api.reviewGrade(examId, payload);
      setItems(prev => prev.filter((_, i) => i !== cursor));
      setCursor(prev => Math.min(prev, items.length - 2));
      showToast(action === 'approve' ? '✓ Approved' : '✏ Overridden');
    } catch (err) { setError(err.message); }
  }, [current, cursor, examId, items.length, user]);

  /* ── Bulk approve all ── */
  async function bulkApproveAll() {
    const ids = items.map(i => i.grade.grade_id);
    if (!ids.length) return;
    try {
      await api.bulkApprove(examId, { grade_ids: ids, ta_id: user.user_id });
      setItems([]);
      showToast(`✓ Approved all ${ids.length} grades`);
    } catch (err) { setError(err.message); }
  }

  /* ── Keyboard shortcuts ── */
  useEffect(() => {
    function onKey(e) {
      if (!items.length || override.open) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      switch (e.key.toLowerCase()) {
        case 'a': doReview('approve'); break;
        case 'o': setOverride({ open: true, score: '', note: '' }); break;
        case 'arrowdown':
        case 'j': e.preventDefault(); setCursor(p => Math.min(p + 1, items.length - 1)); break;
        case 'arrowup':
        case 'k': e.preventDefault(); setCursor(p => Math.max(p - 1, 0)); break;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [items, override.open, doReview]);

  /* ── Render ── */
  return (
    <div className="review-page animate-in">
      {/* Toast */}
      {toast && <div className="review-toast animate-in">{toast}</div>}

      <div className="page-header">
        <div className="flex justify-between items-center">
          <div>
            <h1>Review Dashboard</h1>
            <p>Keyboard shortcuts: <kbd className="kbd">A</kbd> Approve &nbsp;
               <kbd className="kbd">O</kbd> Override &nbsp;
               <kbd className="kbd">↑↓</kbd> Navigate</p>
          </div>
          {items.length > 0 && (
            <button className="btn btn-ghost btn-sm" onClick={bulkApproveAll}>
              ✓ Approve All ({items.length})
            </button>
          )}
        </div>
      </div>

      {/* Exam ID input */}
      <div className="card mb-4">
        <div className="lookup-row">
          <input type="text" className="form-input"
            placeholder="Exam ID to review"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && (setExamId(input), loadDashboard(input))}
          />
          <button className="btn btn-primary"
            onClick={() => { setExamId(input); loadDashboard(input); }}
            disabled={loading}>
            {loading ? <span className="spinner" /> : 'Load'}
          </button>
        </div>
        {error && <div className="alert alert-error mt-4">{error}</div>}
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="stats-bar">
          <span>Total: <b>{stats.total}</b></span>
          <span>Pending: <b className="text-gold">{items.length}</b></span>
          {stats.total > 0 && (
            <div className="progress-wrap">
              <div className="progress-bar"
                style={{ width: `${((stats.total - items.length) / stats.total) * 100}%` }} />
            </div>
          )}
          <span className="text-dim text-sm">
            {stats.total > 0 ? `${(((stats.total - items.length) / stats.total) * 100).toFixed(0)}% reviewed` : ''}
          </span>
        </div>
      )}

      {loading && <div className="loading-center"><div className="spinner spinner-lg" /><span>Loading grades…</span></div>}

      {!loading && items.length === 0 && examId && (
        <div className="empty-state mt-6">
          <div className="icon">🎉</div>
          <h3>All caught up!</h3>
          <p>No pending grades to review for this exam.</p>
        </div>
      )}

      {!loading && items.length > 0 && (
        <div className="review-layout">
          {/* Grade list (left) */}
          <div className="grade-list">
            {items.map((item, idx) => (
              <div
                key={item.grade.grade_id}
                className={`grade-list-item ${idx === cursor ? 'active' : ''} ${item.grade.plagiarism_flag ? 'plagiarism' : ''}`}
                onClick={() => setCursor(idx)}
              >
                <div className="flex justify-between items-center">
                  <span className="mono text-sm">{item.grade.student_id}</span>
                  <span className={`badge badge-${item.grade.status}`}>{item.grade.status}</span>
                </div>
                <div className="flex justify-between items-center mt-1">
                  <span className="text-dim text-sm">Q{item.grade.question_number}</span>
                  <span className="mono text-gold">{item.grade.total_awarded}/{item.grade.total_possible}</span>
                </div>
                {item.grade.plagiarism_flag && (
                  <div className="text-sm" style={{ color: 'var(--flagged)', marginTop: 4 }}>
                    ⚠ Plagiarism {(item.grade.plagiarism_similarity * 100).toFixed(0)}%
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Grade detail (right) */}
          {current && (
            <div className="grade-detail animate-in">
              <GradeDetail
                item={current}
                onApprove={() => doReview('approve')}
                onOverride={() => setOverride({ open: true, score: String(current.grade.total_awarded), note: '' })}
              />
            </div>
          )}
        </div>
      )}

      {/* Override modal */}
      {override.open && current && (
        <div className="modal-overlay" onClick={() => setOverride(o => ({...o, open: false}))}>
          <div className="modal-card animate-in" onClick={e => e.stopPropagation()}>
            <h3>Override Grade</h3>
            <p className="text-dim text-sm mt-1">
              Student <b>{current.grade.student_id}</b> — Q{current.grade.question_number}
              (AI score: {current.grade.total_awarded}/{current.grade.total_possible})
            </p>
            <div className="divider" />
            <div className="form-group mt-2">
              <label className="form-label">New Score (max {current.grade.total_possible})</label>
              <input type="number" className="form-input"
                min="0" max={current.grade.total_possible} step="0.5"
                value={override.score}
                onChange={e => setOverride(o => ({...o, score: e.target.value}))}
                autoFocus
              />
            </div>
            <div className="form-group mt-3">
              <label className="form-label">Note (optional)</label>
              <textarea className="form-textarea" style={{ minHeight: 80 }}
                placeholder="Reason for override…"
                value={override.note}
                onChange={e => setOverride(o => ({...o, note: e.target.value}))}
              />
            </div>
            <div className="flex gap-3 mt-4">
              <button className="btn btn-primary" onClick={() => {
                doReview('override', override.score, override.note);
                setOverride({ open: false, score: '', note: '' });
              }}>
                Confirm Override
              </button>
              <button className="btn btn-ghost" onClick={() => setOverride(o => ({...o, open: false}))}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function GradeDetail({ item, onApprove, onOverride }) {
  const { grade } = item;
  const pct = ((grade.total_awarded / grade.total_possible) * 100).toFixed(0);
  const scoreColor = pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--danger)';

  return (
    <>
      <div className="detail-header">
        <div>
          <div className="mono" style={{ fontSize: '1.1rem', color: 'var(--text)' }}>
            {grade.student_id}
          </div>
          <div className="text-dim text-sm">Question {grade.question_number}</div>
        </div>
        <div className="score-ring" style={{ '--score-color': scoreColor }}>
          <span className="score-num">{grade.total_awarded}</span>
          <span className="score-denom">/{grade.total_possible}</span>
        </div>
      </div>

      {grade.plagiarism_flag && (
        <div className="alert alert-warning mt-4">
          ⚠ Possible plagiarism detected — similarity {(grade.plagiarism_similarity * 100).toFixed(0)}%
        </div>
      )}

      {/* Crop image — student's handwritten answer */}
      {item.crop_path && (
        <div className="detail-section mt-4">
          <h4>Student Answer (Cropped)</h4>
          <div className="crop-image-wrap mt-2">
            <img
              src={item.crop_path}
              alt={`Cropped answer for ${grade.student_id} Q${grade.question_number}`}
              className="crop-image"
              onError={e => { e.currentTarget.style.display = 'none'; }}
            />
          </div>
        </div>
      )}

      {/* OCR Text */}
      <div className="detail-section mt-4">
        <h4>Transcribed Answer</h4>
        <div className="ocr-box mt-2">{grade.ocr_text || <span className="text-mute">No text extracted</span>}</div>
      </div>

      {/* Justification */}
      <div className="detail-section mt-4">
        <h4>AI Justification</h4>
        <p className="mt-2" style={{ fontSize: '13.5px', lineHeight: 1.7 }}>
          {grade.overall_justification || '—'}
        </p>
      </div>

      {/* Criterion breakdown */}
      {grade.criterion_scores?.length > 0 && (
        <div className="detail-section mt-4">
          <h4>Criterion Breakdown</h4>
          <div className="criteria-list mt-2">
            {grade.criterion_scores.map(c => (
              <div key={c.criterion_id} className="criterion-row">
                <div className="criterion-desc">{c.justification}</div>
                <div className="criterion-pts mono" style={{ color: scoreColor }}>
                  +{c.awarded_points}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="detail-actions mt-6">
        <button className="btn btn-success" onClick={onApprove}>
          ✓ Approve <kbd className="kbd">A</kbd>
        </button>
        <button className="btn btn-danger" onClick={onOverride}>
          ✏ Override <kbd className="kbd">O</kbd>
        </button>
      </div>
    </>
  );
}
