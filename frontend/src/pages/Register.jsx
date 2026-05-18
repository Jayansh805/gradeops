import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Login.css';

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [form,    setForm]    = useState({ email: '', full_name: '', password: '' });
  const [error,   setError]   = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  function onChange(e) { setForm(f => ({ ...f, [e.target.name]: e.target.value })); }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(''); setSuccess('');
    setLoading(true);
    try {
      await register(form);
      setSuccess('Account created! You can now log in as a TA.');
      setTimeout(() => navigate('/login'), 1800);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-bg-grid" />
      <div className="auth-card animate-in">
        <div className="auth-brand">
          <span className="auth-brand-icon">⚡</span>
          <span className="auth-brand-name">GradeOps</span>
        </div>
        <p className="auth-tagline">Create a TA account</p>
        <div className="divider" />

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label className="form-label">Full Name</label>
            <input name="full_name" type="text" className="form-input"
              placeholder="Dr. Jane Smith" value={form.full_name}
              onChange={onChange} required autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label">Email</label>
            <input name="email" type="email" className="form-input"
              placeholder="you@university.edu" value={form.email}
              onChange={onChange} required />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input name="password" type="password" className="form-input"
              placeholder="••••••••" value={form.password}
              onChange={onChange} required />
          </div>

          <div className="alert alert-info" style={{ fontSize: '12px' }}>
            ℹ All new accounts are registered as <strong>Teaching Assistants</strong>.
            Instructor accounts are promoted by admins.
          </div>

          {error   && <div className="alert alert-error">{error}</div>}
          {success && <div className="alert alert-success">{success}</div>}

          <button type="submit" className="btn btn-primary w-full btn-lg" disabled={loading}>
            {loading ? <><span className="spinner" /> Creating…</> : 'Create Account'}
          </button>
        </form>

        <p className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
