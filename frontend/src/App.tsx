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
                  <PlannedModulePage
                    title="Brand Hub & Versioned Brand Knowledge"
                    phase="Phase 3"
                    owner="Riddhi Yadav & Pathik Talwar"
                    summary="Create and version Brand Kits including Brand Identity, Brand Voice, Approved Brand Facts (prices, specs, offers), Compliance Rules, and Reference Assets."
                    deliverables={[
                      'Brand Identity & Typography configuration',
                      'Structured, versioned Approved Brand Facts (e.g., Premium Coffee = ₹129)',
                      'Prohibited terms, required disclaimers, and restricted claims rules',
                      'Immutable Brand Kit publication and version history binding',
                    ]}
                  />
                </ProtectedRoute>
              }
            />
            <Route
              path="content-upload"
              element={
                <ProtectedRoute requiredPermission="content:create">
                  <PlannedModulePage
                    title="Multimodal Content Ingestion & Extraction"
                    phase="Phase 4"
                    owner="Riddhi Yadav & Tanmay Mishra"
                    summary="Upload plain text, social captions, PDFs, DOCX files, and promotional images with PyMuPDF, python-docx, and OCR extraction."
                    deliverables={[
                      'File size and MIME-type validation',
                      'PyMuPDF and python-docx structured text extraction',
                      'Image OCR extraction with source span preservation',
                      'SHA-256 content revision creation on every upload/edit',
                    ]}
                  />
                </ProtectedRoute>
              }
            />
            <Route
              path="compliance-review"
              element={
                <ProtectedRoute requiredPermission="content:review">
                  <PlannedModulePage
                    title="Hybrid Deterministic + LangGraph RAG Compliance Engine"
                    phase="Phase 5 – Phase 7"
                    owner="Pathik Talwar, Tanmay Mishra & Pragati Kumari"
                    summary="Combines exact deterministic rule evaluation with pgvector RAG retrieval and LangGraph semantic verification."
                    deliverables={[
                      'Deterministic checks for exact prices, prohibited words, and required disclaimers',
                      '1024-d BAAI/bge-large-en-v1.5 embeddings & tenant-isolated pgvector retrieval',
                      '11-node LangGraph orchestration with Pydantic v2 output validation',
                      'Explicit UNVERIFIED fallback when approved evidence is unavailable',
                    ]}
                  />
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
                <ProtectedRoute requiredPermission="approval:decide">
                  <PlannedModulePage
                    title="Human Approval Gate & Reviewer Inbox"
                    phase="Phase 8"
                    owner="Pragati Kumari & Pathik Talwar"
                    summary="Enforce DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED / REJECTED / REVISION_REQUESTED workflow bound to exact revision and SHA-256 hash."
                    deliverables={[
                      'Cryptographic SHA-256 revision verification before approval',
                      'Role-based Reviewer/Approver permission checks',
                      'Reviewer comments, rejection reasons, and revision requests',
                    ]}
                  />
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
