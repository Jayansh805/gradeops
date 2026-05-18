import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import Register from './pages/Register';
import UploadExam from './pages/instructor/UploadExam';
import ExamsList from './pages/instructor/ExamsList';
import ReviewDashboard from './pages/ta/ReviewDashboard';
import PlagiarismView from './pages/ta/PlagiarismView';

function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === 'instructor' ? '/instructor/exams' : '/ta/review'} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login"    element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* Instructor */}
          <Route path="/instructor/upload" element={
            <ProtectedRoute role="instructor">
              <Layout><UploadExam /></Layout>
            </ProtectedRoute>
          } />
          <Route path="/instructor/exams" element={
            <ProtectedRoute role="instructor">
              <Layout><ExamsList /></Layout>
            </ProtectedRoute>
          } />

          {/* TA */}
          <Route path="/ta/review" element={
            <ProtectedRoute role="ta">
              <Layout><ReviewDashboard /></Layout>
            </ProtectedRoute>
          } />
          <Route path="/ta/plagiarism" element={
            <ProtectedRoute role="ta">
              <Layout><PlagiarismView /></Layout>
            </ProtectedRoute>
          } />

          {/* Root */}
          <Route path="/" element={<RootRedirect />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
