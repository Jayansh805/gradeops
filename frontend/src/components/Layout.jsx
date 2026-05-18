import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Layout.css';

const INSTRUCTOR_NAV = [
  { to: '/instructor/upload', icon: '⬆', label: 'Upload Exam' },
  { to: '/instructor/exams',  icon: '📋', label: 'My Exams' },
];

const TA_NAV = [
  { to: '/ta/review',      icon: '✅', label: 'Review Grades' },
  { to: '/ta/plagiarism',  icon: '🔍', label: 'Plagiarism' },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const isInstructor = user?.role === 'instructor';
  const nav = isInstructor ? INSTRUCTOR_NAV : TA_NAV;

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <div className="layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-icon">⚡</span>
          <span className="brand-name">GradeOps</span>
        </div>

        <div className="sidebar-role">
          <span className="role-badge">{user?.role?.toUpperCase()}</span>
        </div>

        <nav className="sidebar-nav">
          {nav.map(({ to, icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'nav-item--active' : ''}`
              }
            >
              <span className="nav-icon">{icon}</span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-info">
            <div className="user-avatar">
              {user?.full_name?.[0]?.toUpperCase() || '?'}
            </div>
            <div className="user-details">
              <div className="user-name">{user?.full_name}</div>
              <div className="user-email">{user?.email}</div>
            </div>
          </div>
          <button className="logout-btn" onClick={handleLogout} title="Logout">
            ⏏
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="main-content">
        <div className="page-wrapper">
          {children}
        </div>
      </main>
    </div>
  );
}
