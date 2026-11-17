import React, { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import {
  ShieldCheck,
  Lock,
  Mail,
  AlertCircle,
  ArrowRight,
  Loader2,
  Sparkles,
  Shield,
  Upload,
  FileSearch,
  Cpu,
  FileCheck2,
  UserCheck,
  CheckCircle,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useBackendHealth } from '../hooks/useBackendHealth';
import { BackendStatusBadge } from '../components/BackendStatusBadge';

export const LoginPage: React.FC = () => {
  const { user, login, sessionError } = useAuth();
  const { health, loading: healthLoading, error: healthError, lastChecked, refresh } = useBackendHealth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);

  const searchParams = new URLSearchParams(location.search);
  const redirectParam = searchParams.get('redirect');
  const targetDestination =
    redirectParam ||
    (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ||
    '/';

  if (user) {
    return <Navigate to={targetDestination} replace />;
  }

  const handleSelectDemoAccount = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword('');
    setError(null);
    setInfoMessage('Account selected. Please enter the password provided privately to hackathon evaluators.');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMessage(null);
    if (!email.trim() || !password) {
      setError('Please enter both your work email address and password.');
      return;
    }

    setSubmitting(true);
    try {
      await login(email.trim().toLowerCase(), password);
      navigate(targetDestination, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed. Please verify credentials.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#212121] text-[#ECECEC] flex flex-col justify-between p-4 sm:p-6 lg:p-8 antialiased selection:bg-[#10A37F]/30">
      {/* Top Navigation / Brand Header */}
      <header className="max-w-7xl w-full mx-auto flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-[#424242]/40">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#2F2F2F] border border-[#424242] text-[#10A37F] shadow-sm">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-lg text-[#ECECEC] tracking-tight">Inkloom AI</span>
              <span className="rounded bg-[#10A37F]/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#10A37F] border border-[#10A37F]/30">
                CodeTitans Round 3
              </span>
            </div>
            <p className="text-xs text-[#A1A1AA]">Enterprise Brand Compliance & Review Platform</p>
          </div>
        </div>
        <BackendStatusBadge
          health={health}
          loading={healthLoading}
          error={healthError}
          lastChecked={lastChecked}
          onRefresh={refresh}
        />
      </header>

      {/* Main Split-Screen Workspace */}
      <main className="max-w-7xl w-full mx-auto my-auto py-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-start">
          {/* Left Column: Product Introduction, 5-Step Workflow, Benefits */}
          <div className="lg:col-span-7 space-y-6">
            {/* 1. Product Introduction */}
            <div className="space-y-3">
              <div className="inline-flex items-center gap-1.5 rounded-full border border-[#10A37F]/30 bg-[#10A37F]/10 px-3 py-1 text-xs font-medium text-[#10A37F]">
                <Sparkles className="h-3.5 w-3.5" />
                <span>Next-Gen Enterprise Brand Governance</span>
              </div>
              <h1 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-[#ECECEC] leading-tight">
                Every Brand. Every Asset. <span className="text-[#10A37F]">Always Compliant.</span>
              </h1>
              <p className="text-sm text-[#A1A1AA] leading-relaxed max-w-2xl">
                Inkloom AI unifies authoritative deterministic policy verification, multimodal guideline document processing, and maker-checker human authorization into an immutable enterprise compliance workbench.
              </p>
            </div>

            {/* 2. Five-Step Workflow Architecture */}
            <div className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-5 space-y-4">
              <div className="flex items-center justify-between border-b border-[#424242] pb-3">
                <div className="flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-[#10A37F]" />
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-[#ECECEC]">
                    Five-Step Workflow Architecture
                  </h2>
                </div>
                <span className="text-[10px] text-[#A1A1AA] font-mono">End-to-End Governance</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
                {/* Step 1: Content Upload */}
                <div className="rounded-lg border border-[#424242] bg-[#212121] p-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-[#10A37F] font-bold">01</span>
                    <Upload className="h-3.5 w-3.5 text-[#10A37F]" />
                  </div>
                  <h3 className="text-xs font-semibold text-[#ECECEC]">Content Upload</h3>
                  <p className="text-[11px] text-[#A1A1AA] leading-snug">
                    Ingest marketing copy, drafts, and campaign assets.
                  </p>
                </div>

                {/* Step 2: Document Processing */}
                <div className="rounded-lg border border-[#424242] bg-[#212121] p-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-[#10A37F] font-bold">02</span>
                    <FileSearch className="h-3.5 w-3.5 text-[#10A37F]" />
                  </div>
                  <h3 className="text-xs font-semibold text-[#ECECEC]">Document Processing</h3>
                  <p className="text-[11px] text-[#A1A1AA] leading-snug">
                    OCR and guideline extraction for PDF, TXT, and images.
                  </p>
                </div>

                {/* Step 3: Compliance Analysis */}
                <div className="rounded-lg border border-[#424242] bg-[#212121] p-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-[#10A37F] font-bold">03</span>
                    <Cpu className="h-3.5 w-3.5 text-[#10A37F]" />
                  </div>
                  <h3 className="text-xs font-semibold text-[#ECECEC]">Compliance Analysis</h3>
                  <p className="text-[11px] text-[#A1A1AA] leading-snug">
                    Deterministic policy gate & 1024-dim vector retrieval.
                  </p>
                </div>

                {/* Step 4: Evidence-Linked Findings */}
                <div className="rounded-lg border border-[#424242] bg-[#212121] p-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-[#10A37F] font-bold">04</span>
                    <FileCheck2 className="h-3.5 w-3.5 text-[#10A37F]" />
                  </div>
                  <h3 className="text-xs font-semibold text-[#ECECEC]">Evidence-Linked Findings</h3>
                  <p className="text-[11px] text-[#A1A1AA] leading-snug">
                    Character span citations with severity scoring.
                  </p>
                </div>

                {/* Step 5: Human-Gated Approval */}
                <div className="rounded-lg border border-[#424242] bg-[#212121] p-3 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-[#10A37F] font-bold">05</span>
                    <UserCheck className="h-3.5 w-3.5 text-[#10A37F]" />
                  </div>
                  <h3 className="text-xs font-semibold text-[#ECECEC]">Human-Gated Approval</h3>
                  <p className="text-[11px] text-[#A1A1AA] leading-snug">
                    Maker-checker review with immutable audit logging.
                  </p>
                </div>
              </div>
            </div>

            {/* 3. Benefits Section */}
            <div className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-5 space-y-3.5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[#A1A1AA]">
                Core Enterprise Benefits
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div className="flex items-start gap-2.5 rounded-lg border border-[#424242] bg-[#212121] p-3">
                  <CheckCircle className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-semibold text-[#ECECEC]">Consistent brand compliance</h4>
                    <p className="text-[11px] text-[#A1A1AA] leading-relaxed mt-0.5">
                      Enforce unified guidelines and regulatory rules across all marketing assets and channels.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 rounded-lg border border-[#424242] bg-[#212121] p-3">
                  <CheckCircle className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-semibold text-[#ECECEC]">Evidence-backed detection</h4>
                    <p className="text-[11px] text-[#A1A1AA] leading-relaxed mt-0.5">
                      Map violations to exact character spans, rule IDs, and retrieved guideline chunks.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 rounded-lg border border-[#424242] bg-[#212121] p-3">
                  <CheckCircle className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-semibold text-[#ECECEC]">Faster remediation</h4>
                    <p className="text-[11px] text-[#A1A1AA] leading-relaxed mt-0.5">
                      1-click suggested corrections and instant side-by-side diff comparison across revisions.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 rounded-lg border border-[#424242] bg-[#212121] p-3">
                  <CheckCircle className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-semibold text-[#ECECEC]">Independent human approval</h4>
                    <p className="text-[11px] text-[#A1A1AA] leading-relaxed mt-0.5">
                      Maker-checker security separating copy submitters from authorized compliance reviewers.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-2.5 rounded-lg border border-[#424242] bg-[#212121] p-3 sm:col-span-2">
                  <CheckCircle className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-semibold text-[#ECECEC]">Complete auditability</h4>
                    <p className="text-[11px] text-[#A1A1AA] leading-relaxed mt-0.5">
                      Cryptographically bound audit trail recording every submission, revision, and reviewer decision.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Existing Login Form & Quick Demos */}
          <div className="lg:col-span-5 w-full max-w-md mx-auto">
            <div className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-6 sm:p-8 shadow-xl space-y-6">
              <div className="space-y-1">
                <h2 className="text-xl font-semibold text-[#ECECEC] tracking-tight">Sign in to Workspace</h2>
                <p className="text-xs text-[#A1A1AA] leading-relaxed">
                  Authenticate into your organisation workspace to access Brand Kits, review workflows, and approval queues.
                </p>
              </div>

              {(error || sessionError) && (
                <div className="rounded-lg border border-[#EF4444]/40 bg-[#EF4444]/10 p-3 text-xs text-[#EF4444] flex items-start gap-2.5">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span className="font-medium">{error || sessionError}</span>
                </div>
              )}

              {infoMessage && (
                <div className="rounded-lg border border-[#10A37F]/40 bg-[#10A37F]/10 p-3 text-xs text-[#ECECEC] flex items-start gap-2.5">
                  <Shield className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
                  <span className="font-medium">{infoMessage}</span>
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4" noValidate>
                <div>
                  <label htmlFor="login-email" className="block text-xs font-medium text-[#ECECEC] mb-1.5 uppercase tracking-wider">
                    Work Email Address
                  </label>
                  <div className="relative">
                    <Mail className="h-4 w-4 text-[#71717A] absolute left-3.5 top-3" />
                    <input
                      id="login-email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="judge@inkloom.ai"
                      className="w-full rounded-lg border border-[#424242] bg-[#212121] pl-10 pr-3.5 py-2 text-sm text-[#ECECEC] placeholder-[#71717A] focus:border-[#10A37F] focus:outline-none transition"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="login-password" className="block text-xs font-medium text-[#ECECEC] mb-1.5 uppercase tracking-wider">
                    Password
                  </label>
                  <div className="relative">
                    <Lock className="h-4 w-4 text-[#71717A] absolute left-3.5 top-3" />
                    <input
                      id="login-password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••"
                      className="w-full rounded-lg border border-[#424242] bg-[#212121] pl-10 pr-3.5 py-2 text-sm text-[#ECECEC] placeholder-[#71717A] focus:border-[#10A37F] focus:outline-none transition"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-[#10A37F] hover:bg-[#0D8F70] px-4 py-2 text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
                >
                  {submitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>Authenticating Session...</span>
                    </>
                  ) : (
                    <>
                      <span>Sign In</span>
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </form>

              {/* Quick Demo Credentials Assistant */}
              <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-[#ECECEC] flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-[#10A37F]" />
                    <span>Quick Evaluation Logins</span>
                  </span>
                  <span className="text-[10px] text-[#71717A] font-mono">Select Account</span>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleSelectDemoAccount('judge@inkloom.ai')}
                    className="text-left p-2 rounded-lg border border-[#424242] bg-[#2F2F2F] hover:bg-[#424242] transition group"
                  >
                    <div className="text-[11px] font-medium text-[#ECECEC] flex items-center justify-between">
                      <span>Judge Account</span>
                      <span className="text-[9px] font-mono text-[#10A37F] border border-[#10A37F]/40 rounded px-1">Admin</span>
                    </div>
                    <div className="text-[10px] text-[#A1A1AA] truncate mt-0.5">judge@inkloom.ai</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSelectDemoAccount('independent_reviewer@inkloom.ai')}
                    className="text-left p-2 rounded-lg border border-[#424242] bg-[#2F2F2F] hover:bg-[#424242] transition group"
                  >
                    <div className="text-[11px] font-medium text-[#ECECEC] flex items-center justify-between">
                      <span>Reviewer</span>
                      <span className="text-[9px] font-mono text-[#10A37F] border border-[#10A37F]/40 rounded px-1">Reviewer</span>
                    </div>
                    <div className="text-[10px] text-[#A1A1AA] truncate mt-0.5">independent_reviewer...</div>
                  </button>
                </div>

                <div className="text-[10px] text-[#A1A1AA] flex items-center gap-1.5 pt-0.5">
                  <Shield className="h-3 w-3 text-[#10A37F] shrink-0" />
                  <span>Passwords are distributed privately to evaluators. Please enter assigned password above.</span>
                </div>
              </div>

              <div className="pt-1 text-center text-xs text-[#A1A1AA]">
                New organisation workspace?{' '}
                <Link to="/register" className="font-medium text-[#10A37F] hover:underline transition">
                  Create an account
                </Link>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="max-w-7xl w-full mx-auto flex flex-wrap items-center justify-between gap-4 text-xs text-[#71717A] pt-4 border-t border-[#424242]/40">
        <div className="flex items-center gap-2">
          <Shield className="h-3.5 w-3.5 text-[#10A37F]" />
          <span>Argon2id Password Hashing • Signed JWT Access Control</span>
        </div>
        <div>
          <span>Multi-Tenant RBAC & PostgreSQL pgvector Architecture</span>
        </div>
      </footer>
    </div>
  );
};

export default LoginPage;
