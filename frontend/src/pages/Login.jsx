import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Login.css';

export default function Login() {
  const { login } = useAuth();
  const navigate   = useNavigate();

  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const user = await login(email, password);
      navigate(user.role === 'instructor' ? '/instructor/exams' : '/ta/review', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function fillDemo(role) {
    setEmail(role === 'instructor' ? 'instructor@gradeops.dev' : 'ta@gradeops.dev');
    setPassword(role === 'instructor' ? 'instructor123' : 'ta123');
    setError('');
  }

  return (
    <div className="auth-page">
      <div className="auth-bg-grid" />

      <div className="auth-card animate-in">
        <div className="auth-brand">
          <span className="auth-brand-icon">⚡</span>
          <span className="auth-brand-name">GradeOps</span>
        </div>

        <p className="auth-tagline">AI-Powered Exam Grading Pipeline</p>

        <div className="demo-pills">
          <button className="demo-pill" onClick={() => fillDemo('instructor')}>
            Use Instructor Demo
          </button>
          <button className="demo-pill" onClick={() => fillDemo('ta')}>
            Use TA Demo
          </button>
        </div>

        <div className="divider" />

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label className="form-label">Email</label>
            <input
              type="email"
              className="form-input"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              type="password"
              className="form-input"
              placeholder="••••••••"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>

          {error && <div className="alert alert-error">{error}</div>}

          <button
            type="submit"
            className="btn btn-primary w-full btn-lg"
            disabled={loading}
          >
            {loading ? <><span className="spinner" /> Signing in…</> : 'Sign In'}
          </button>
        </form>

        <p className="auth-footer">
          No account?{' '}
          <Link to="/register">Register here</Link>
        </p>
      </div>
    </div>
  );
}
