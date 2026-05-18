import { useState } from 'react';
import api from '../../api/client';

export default function PlagiarismView() {
  const [examId,    setExamId]    = useState('');
  const [minScore,  setMinScore]  = useState(0);
  const [data,      setData]      = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState('');

  async function load() {
    if (!examId.trim()) { setError('Enter an exam ID.'); return; }
    setError(''); setLoading(true); setData(null);
    try {
      const res = await api.getPlagiarism(examId.trim(), minScore / 100);
      setData(res);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  return (
    <div className="animate-in">
      <div className="page-header">
        <h1>Plagiarism Detector</h1>
        <p>View AI-flagged similar submissions for an exam.</p>
      </div>

      <div className="card">
        <div style={{ display:'flex', gap:10, alignItems:'center', flexWrap:'wrap' }}>
          <input type="text" className="form-input" style={{ flex:1, minWidth:200 }}
            placeholder="Exam ID"
            value={examId} onChange={e => setExamId(e.target.value)}
            onKeyDown={e => e.key==='Enter' && load()} />
          <div style={{ display:'flex', alignItems:'center', gap:8, whiteSpace:'nowrap' }}>
            <label className="form-label" style={{ marginBottom:0 }}>Min similarity</label>
            <input type="number" className="form-input" style={{ width:80 }}
              min={0} max={100} step={5}
              value={minScore} onChange={e => setMinScore(Number(e.target.value))} />
            <span className="text-dim">%</span>
          </div>
          <button className="btn btn-primary" onClick={load} disabled={loading}>
            {loading ? <span className="spinner" /> : 'Scan'}
          </button>
        </div>
        {error && <div className="alert alert-error mt-4">{error}</div>}
      </div>

      {data && (
        <div className="mt-6 animate-in">
          <div className="card card-sm" style={{ display:'flex', gap:24, alignItems:'center' }}>
            <div>
              <div className="mono" style={{ fontSize:'2rem', color: data.flagged_count > 0 ? 'var(--flagged)' : 'var(--success)' }}>
                {data.flagged_count}
              </div>
              <div className="text-mute text-sm">flagged submissions</div>
            </div>
            <div className="divider" style={{ height:40, width:1, margin:0 }} />
            <div className="text-dim text-sm">
              Exam: <code>{data.exam_id}</code>
            </div>
          </div>

          {data.flagged_count === 0 ? (
            <div className="empty-state mt-6">
              <div className="icon">✅</div>
              <h3>No plagiarism detected</h3>
              <p>All submissions appear to be unique at the ≥{minScore}% threshold.</p>
            </div>
          ) : (
            <div className="card mt-4 table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Student ID</th>
                    <th>Question</th>
                    <th>Similarity</th>
                    <th>Status</th>
                    <th>Justification</th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((r, i) => (
                    <tr key={i}>
                      <td className="mono">{r.student_id}</td>
                      <td className="mono">Q{r.question_number}</td>
                      <td>
                        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                          <div style={{
                            width: 60, height: 6,
                            background: 'var(--border)',
                            borderRadius: 3,
                            overflow: 'hidden',
                          }}>
                            <div style={{
                              width: `${r.plagiarism_similarity*100}%`,
                              height:'100%',
                              background: r.plagiarism_similarity > 0.9
                                ? 'var(--danger)'
                                : r.plagiarism_similarity > 0.75
                                  ? 'var(--warning)'
                                  : 'var(--flagged)',
                            }} />
                          </div>
                          <span className="mono text-sm">{(r.plagiarism_similarity*100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td><span className="badge badge-flagged">{r.status}</span></td>
                      <td className="text-dim text-sm" style={{ maxWidth:300 }}>
                        {r.overall_justification?.slice(0, 120) || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!data && !loading && (
        <div className="empty-state mt-6">
          <div className="icon">🔍</div>
          <h3>No scan run yet</h3>
          <p>Enter an exam ID above to check for plagiarism flags.</p>
        </div>
      )}
    </div>
  );
}
