import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import { ProtectedRoute } from './components/ProtectedRoute';
import { AppLayout } from './layouts/AppLayout';
import { DashboardHome } from './pages/DashboardHome';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { AcceptInvitationPage } from './pages/AcceptInvitationPage';
import { OrganisationSettingsPage } from './pages/OrganisationSettingsPage';
import { PlannedModulePage } from './pages/PlannedModulePage';
import { BrandRulesPage } from './pages/BrandRulesPage';
import { ComplianceWorkbenchPage } from './pages/ComplianceWorkbenchPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { ContentUploadPage } from './pages/ContentUploadPage';

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/accept-invitation" element={<AcceptInvitationPage />} />

          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<DashboardHome />} />
            <Route
              path="settings"
              element={
                <ProtectedRoute requiredPermission="users:read">
                  <OrganisationSettingsPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="brand-hub"
              element={
                <ProtectedRoute requiredPermission="brand:read">
                  <BrandRulesPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="content-upload"
              element={
                <ProtectedRoute requiredPermission="content:create">
                  <ContentUploadPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="compliance-review"
              element={
                <ProtectedRoute requiredPermission="content:review">
                  <ComplianceWorkbenchPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="content-editor"
              element={
                <ProtectedRoute requiredPermission="content:edit">
                  <PlannedModulePage
                    title="Integrated Content Editor & AI Corrections"
                    phase="Phase 7"
                    owner="Pragati Kumari"
                    summary="Inspect highlighted violations, apply evidence-backed suggested corrections, compare revisions, and re-run compliance checks."
                    deliverables={[
                      'Inline violation highlighting mapped to exact character spans',
                      'One-click application of recommended corrections',
                      'Automatic creation of new SHA-256 content revision on edit',
                      'Automatic invalidation of prior approvals upon content modification',
                    ]}
                  />
                </ProtectedRoute>
              }
            />
            <Route
              path="approvals"
              element={
                <ProtectedRoute requiredPermission="content:review">
                  <ApprovalsPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="audit-logs"
              element={
                <ProtectedRoute requiredPermission="audit:read">
                  <PlannedModulePage
                    title="Append-Only Security Audit Logs"
                    phase="Phase 8"
                    owner="Pathik Talwar"
                    summary="Immutable audit trail recording actor, organisation, action, target resource, and version deltas across the platform."
                    deliverables={[
                      'Append-only audit records for auth, Brand Kit publication, reviews, and approvals',
                      'Tenant-scoped audit querying for Organisation Admins',
                    ]}
                  />
                </ProtectedRoute>
              }
            />
            <Route
              path="analytics"
              element={
                <ProtectedRoute requiredPermission="content:review">
                  <PlannedModulePage
                    title="Database-Backed Compliance Analytics & Reports"
                    phase="Phase 9"
                    owner="Pragati Kumari"
                    summary="Real-time analytics computed strictly from database records: violation categories, severity distributions, and approval rates."
                    deliverables={[
                      'Compliance score trend aggregations',
                      'Violation category and severity breakdowns',
                      'Exportable compliance summary reports',
                    ]}
                  />
                </ProtectedRoute>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
