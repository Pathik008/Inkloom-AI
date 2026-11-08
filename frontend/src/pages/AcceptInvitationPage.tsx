import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ShieldCheck,
  Building2,
  Mail,
  Lock,
  User,
  AlertCircle,
  CheckCircle2,
  Loader2,
  ArrowRight,
  LogOut,
  Clock,
  Ban,
  Check,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useBackendHealth } from '../hooks/useBackendHealth';
import { BackendStatusBadge } from '../components/BackendStatusBadge';
import {
  acceptInvitation,
  getInvitationDetails,
  registerAndAcceptInvitation,
} from '../services/api';
import { InvitationPublicDetail } from '../types';

export const AcceptInvitationPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const navigate = useNavigate();

  const { user, logout, switchOrganisation, refreshUser, applyAuthSession } = useAuth();
  const { health, loading: healthLoading, error: healthError, lastChecked, refresh } =
    useBackendHealth();

  const [loading, setLoading] = useState<boolean>(true);
  const [invitation, setInvitation] = useState<InvitationPublicDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Authenticated acceptance state
  const [accepting, setAccepting] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Unauthenticated registration state
  const [fullName, setFullName] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [registering, setRegistering] = useState<boolean>(false);

  useEffect(() => {
    let active = true;

    if (!token.trim()) {
      setLoadError('Invalid invitation link: missing invitation token.');
      setLoading(false);
      return;
    }

    async function fetchDetail() {
      setLoading(true);
      setLoadError(null);
      try {
        const detail = await getInvitationDetails(token.trim());
        if (active) {
          setInvitation(detail);
        }
      } catch (err) {
        if (active) {
          setLoadError(
            err instanceof Error
              ? err.message
              : 'Unable to load invitation. The link may be expired, revoked, or invalid.',
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void fetchDetail();

    return () => {
      active = false;
    };
  }, [token]);

  const handleAuthenticatedAccept = async () => {
    if (!token.trim()) return;
    setAccepting(true);
    setActionError(null);
    try {
      const resp = await acceptInvitation(token.trim());
      setActionSuccess(
        `Successfully joined ${resp.organisation_name} as ${resp.role}. Redirecting to workspace...`,
      );
      await switchOrganisation(resp.organisation_id);
      await refreshUser();
      setTimeout(() => {
        navigate('/', { replace: true });
      }, 1200);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to accept invitation. Please try again.',
      );
    } finally {
      setAccepting(false);
    }
  };

  const handleRegisterAndAccept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    setActionError(null);

    if (!fullName.trim()) {
      setActionError('Please enter your full name.');
      return;
    }
    if (password.length < 8) {
      setActionError('Password must be at least 8 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setActionError('Passwords do not match.');
      return;
    }

    setRegistering(true);
    try {
      const authResp = await registerAndAcceptInvitation(token.trim(), {
        full_name: fullName.trim(),
        password,
        confirm_password: confirmPassword,
      });
      applyAuthSession(authResp);
      setActionSuccess(
        `Account created! Welcome to ${invitation?.organisation_name || 'the workspace'}. Redirecting...`,
      );
      setTimeout(() => {
        navigate('/', { replace: true });
      }, 1000);
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : 'Registration and acceptance failed. Please try again.',
      );
    } finally {
      setRegistering(false);
    }
  };

  const isEmailMatch =
    user && invitation && user.email.trim().toLowerCase() === invitation.email.trim().toLowerCase();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between p-6">
      <header className="max-w-6xl w-full mx-auto flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600/20 border border-indigo-500/40 text-indigo-400">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <span className="font-bold text-lg text-white tracking-tight">Inkloom AI</span>
            <p className="text-xs text-slate-400">Enterprise Brand Compliance Platform</p>
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

      <main className="flex-1 flex items-center justify-center py-12 px-4">
        <div className="w-full max-w-lg space-y-6">
          {/* Loading View */}
          {loading && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur p-8 shadow-2xl text-center space-y-4">
              <Loader2 className="h-8 w-8 text-indigo-400 animate-spin mx-auto" />
              <p className="text-sm text-slate-300">Verifying secure invitation token...</p>
            </div>
          )}

          {/* Load Error View */}
          {!loading && loadError && (
            <div className="rounded-2xl border border-rose-500/30 bg-slate-900/60 backdrop-blur p-8 shadow-2xl space-y-5 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-400">
                <AlertCircle className="h-6 w-6" />
              </div>
              <div className="space-y-1">
                <h3 className="text-lg font-bold text-white">Invalid or Expired Invitation</h3>
                <p className="text-xs text-slate-400">{loadError}</p>
              </div>
              <div className="pt-2 flex justify-center gap-3">
                <Link
                  to="/login"
                  className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition"
                >
                  Go to Login
                </Link>
                <Link
                  to="/"
                  className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
                >
                  Return to Dashboard
                </Link>
              </div>
            </div>
          )}

          {/* Invitation Details / Inactive Statuses */}
          {!loading && invitation && invitation.status !== 'PENDING' && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur p-8 shadow-2xl space-y-5 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-800 border border-slate-700 text-slate-300">
                {invitation.status === 'ACCEPTED' ? (
                  <Check className="h-6 w-6 text-emerald-400" />
                ) : invitation.status === 'REVOKED' ? (
                  <Ban className="h-6 w-6 text-rose-400" />
                ) : (
                  <Clock className="h-6 w-6 text-amber-400" />
                )}
              </div>
              <div className="space-y-1">
                <h3 className="text-lg font-bold text-white">
                  Invitation {invitation.status === 'ACCEPTED' ? 'Already Accepted' : invitation.status === 'REVOKED' ? 'Revoked' : 'Expired'}
                </h3>
                <p className="text-xs text-slate-400">
                  This invitation to join <strong className="text-white">{invitation.organisation_name}</strong> as <span className="font-mono text-indigo-300">{invitation.role}</span> is currently marked as <span className="font-mono font-semibold">{invitation.status}</span>.
                </p>
                {invitation.status === 'EXPIRED' && (
                  <p className="text-[11px] text-slate-500">
                    Expired on {new Date(invitation.expires_at).toLocaleString()}. Please request an organisation administrator to issue a new invitation.
                  </p>
                )}
              </div>
              <div className="pt-2 flex justify-center gap-3">
                <Link
                  to="/login"
                  className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition"
                >
                  Sign In
                </Link>
              </div>
            </div>
          )}

          {/* Active Pending Invitation Content */}
          {!loading && invitation && invitation.status === 'PENDING' && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur p-8 shadow-2xl space-y-6">
              {/* Workspace Header */}
              <div className="text-center space-y-2">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600/20 border border-indigo-500/40 text-indigo-400">
                  <Building2 className="h-6 w-6" />
                </div>
                <h2 className="text-xl font-bold text-white tracking-tight">
                  Join {invitation.organisation_name}
                </h2>
                <p className="text-xs text-slate-400">
                  You have been invited to collaborate as{' '}
                  <span className="rounded bg-indigo-500/20 px-2 py-0.5 font-mono text-indigo-300 font-semibold">
                    {invitation.role}
                  </span>
                </p>
              </div>

              {/* Status/Error Messages */}
              {actionError && (
                <div className="rounded-xl border border-rose-500/40 bg-rose-950/30 p-3.5 text-xs text-rose-200 flex items-center gap-2.5">
                  <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
                  <span>{actionError}</span>
                </div>
              )}
              {actionSuccess && (
                <div className="rounded-xl border border-emerald-500/40 bg-emerald-950/30 p-3.5 text-xs text-emerald-200 flex items-center gap-2.5">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                  <span>{actionSuccess}</span>
                </div>
              )}

              {/* State A: User is logged in */}
              {user ? (
                <div className="space-y-5">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-2 text-xs">
                    <div className="text-slate-400">Currently signed in as:</div>
                    <div className="font-semibold text-white text-sm">{user.full_name}</div>
                    <div className="font-mono text-indigo-300">{user.email}</div>
                  </div>

                  {isEmailMatch ? (
                    <div className="space-y-4">
                      <p className="text-xs text-slate-300 text-center">
                        Your account email matches the invitation recipient ({invitation.email}). Click below to accept and enter the workspace.
                      </p>
                      <button
                        type="button"
                        onClick={handleAuthenticatedAccept}
                        disabled={accepting || !!actionSuccess}
                        className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-500 transition disabled:opacity-50 shadow-lg shadow-indigo-600/30"
                      >
                        {accepting ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            <span>Accepting Invitation...</span>
                          </>
                        ) : (
                          <>
                            <span>Accept Invitation & Enter Workspace</span>
                            <ArrowRight className="h-4 w-4" />
                          </>
                        )}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="rounded-xl border border-amber-500/40 bg-amber-950/30 p-4 text-xs text-amber-200 space-y-2">
                        <div className="font-semibold flex items-center gap-1.5">
                          <AlertCircle className="h-4 w-4 text-amber-400 shrink-0" />
                          <span>Recipient Email Mismatch</span>
                        </div>
                        <p className="text-[11px] leading-relaxed text-amber-300/90">
                          This invitation was sent to <strong className="font-mono text-white">{invitation.email}</strong>, but you are currently signed in as <strong className="font-mono text-white">{user.email}</strong>.
                        </p>
                        <p className="text-[11px] text-slate-300">
                          To maintain strict multi-tenant security, invitations can only be accepted by the intended recipient email.
                        </p>
                      </div>

                      <div className="flex flex-col gap-2.5">
                        <button
                          type="button"
                          onClick={() => void logout()}
                          className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-4 py-2.5 text-xs font-semibold text-slate-200 hover:bg-slate-700 transition"
                        >
                          <LogOut className="h-3.5 w-3.5 text-slate-400" />
                          <span>Sign Out & Switch Account</span>
                        </button>
                        <Link
                          to="/"
                          className="text-center text-xs text-slate-400 hover:text-slate-200 transition py-1"
                        >
                          Return to current workspace
                        </Link>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* State B: User is NOT logged in */
                <div className="space-y-5">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-1 text-xs">
                    <div className="text-slate-400">Invited Recipient:</div>
                    <div className="font-mono text-indigo-300 font-semibold">{invitation.email}</div>
                  </div>

                  {/* Register & Accept Form */}
                  <form onSubmit={handleRegisterAndAccept} className="space-y-3.5">
                    <div className="text-xs font-semibold text-slate-200">
                      Create Your Account to Join
                    </div>

                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Email Address</label>
                      <div className="relative">
                        <Mail className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
                        <input
                          type="email"
                          readOnly
                          value={invitation.email}
                          className="w-full rounded-xl border border-slate-800 bg-slate-950 pl-10 pr-3.5 py-2.5 text-xs text-slate-400 cursor-not-allowed"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs text-slate-300 mb-1">Full Name</label>
                      <div className="relative">
                        <User className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
                        <input
                          type="text"
                          required
                          value={fullName}
                          onChange={(e) => setFullName(e.target.value)}
                          placeholder="Jane Doe"
                          className="w-full rounded-xl border border-slate-700 bg-slate-950 pl-10 pr-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs text-slate-300 mb-1">Password</label>
                        <div className="relative">
                          <Lock className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
                          <input
                            type="password"
                            required
                            minLength={8}
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="Min 8 chars"
                            className="w-full rounded-xl border border-slate-700 bg-slate-950 pl-10 pr-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs text-slate-300 mb-1">Confirm Password</label>
                        <div className="relative">
                          <Lock className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
                          <input
                            type="password"
                            required
                            minLength={8}
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            placeholder="Repeat password"
                            className="w-full rounded-xl border border-slate-700 bg-slate-950 pl-10 pr-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                          />
                        </div>
                      </div>
                    </div>

                    <button
                      type="submit"
                      disabled={registering || !!actionSuccess}
                      className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-500 transition disabled:opacity-50 shadow-lg shadow-indigo-600/30"
                    >
                      {registering ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          <span>Creating Account & Joining...</span>
                        </>
                      ) : (
                        <>
                          <span>Create Account & Join Workspace</span>
                          <ArrowRight className="h-4 w-4" />
                        </>
                      )}
                    </button>
                  </form>

                  <div className="pt-2 border-t border-slate-800 text-center text-xs text-slate-400">
                    Already have an Inkloom account with this email?{' '}
                    <Link
                      to={`/login?redirect=${encodeURIComponent(`/accept-invitation?token=${token}`)}`}
                      className="text-indigo-400 hover:text-indigo-300 font-semibold"
                    >
                      Sign in to accept
                    </Link>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </main>

      <footer className="max-w-6xl w-full mx-auto text-center text-xs text-slate-500 pt-6 border-t border-slate-800">
        Inkloom AI Enterprise Brand Compliance &copy; {new Date().getFullYear()}
      </footer>
    </div>
  );
};
