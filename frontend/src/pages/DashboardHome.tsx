import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import {
  CheckCircle2,
  XCircle,
  Server,
  Database,
  Layers,
  ShieldAlert,
  ArrowRight,
  RefreshCw,
  Clock,
  Cpu,
  FileCheck2,
  Clock4,
  Award,
  BookOpen,
  AlertCircle,
  ShieldCheck,
  Lock,
} from 'lucide-react';
import { HealthStatus, LiveDashboardStats } from '../types';
import { MODULE_ROADMAP } from '../utils/constants';
import {
  fetchBrandKits,
  fetchComplianceMetrics,
  getApiBaseUrl,
} from '../services/api';
import { useAuth } from '../hooks/useAuth';

interface OutletContextType {
  health: HealthStatus | null;
  loading: boolean;
  error: string | null;
  lastChecked: Date | null;
  refresh: () => void;
}

export const DashboardHome: React.FC = () => {
  const { health, loading, error, lastChecked, refresh } = useOutletContext<OutletContextType>();
  const { activeOrganisationId, hasPermission } = useAuth();

  const isApiOnline = Boolean(health && health.status === 'healthy' && !error);
  const canReadBrand = hasPermission('brand:read');
  const canReadContent = hasPermission('content:review');

  const [stats, setStats] = useState<LiveDashboardStats | null>(null);
  const [statsLoading, setStatsLoading] = useState<boolean>(false);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [statsLastUpdated, setStatsLastUpdated] = useState<Date | null>(null);

  // Guard against race conditions when user switches organisations quickly
  const activeOrgRef = useRef<string | null>(activeOrganisationId);
  useEffect(() => {
    activeOrgRef.current = activeOrganisationId;
  }, [activeOrganisationId]);

  const loadLiveStats = useCallback(async () => {
    if (!activeOrganisationId) {
      setStats(null);
      setStatsError(null);
      return;
    }

    const currentOrgId = activeOrganisationId;
    // Clear previous organisation stats immediately to prevent displaying stale metrics
    setStats(null);
    setStatsLoading(true);
    setStatsError(null);

    try {
      // Parallel requests scoped strictly by organization ID and tenant permissions
      const [kitsResult, metricsResult] = await Promise.allSettled([
        canReadBrand ? fetchBrandKits(currentOrgId) : Promise.reject(new Error('PERMISSION_DENIED_BRAND')),
        canReadContent
          ? fetchComplianceMetrics(currentOrgId)
          : Promise.reject(new Error('PERMISSION_DENIED_CONTENT')),
      ]);

      // Check if user switched organization while requests were in-flight
      if (activeOrgRef.current !== currentOrgId) {
        return;
      }

      let activeKitsCount: number | null = null;
      let brandError: string | null = null;

      if (kitsResult.status === 'fulfilled') {
        const kits = kitsResult.value;
        activeKitsCount = kits.filter(
          (k) => !k.is_archived && (Boolean(k.active_version_id) || Boolean(k.active_version)),
        ).length;
      } else {
        const reasonMsg = kitsResult.reason?.message || '';
        if (reasonMsg !== 'PERMISSION_DENIED_BRAND') {
          brandError = kitsResult.reason?.message || 'Failed to fetch brand kits';
        }
      }

      let totalSubmissions: number | null = null;
      let pendingReviews: number | null = null;
      let approvedContent: number | null = null;
      let submissionsError: string | null = null;
      const isCapped = false;

      if (metricsResult.status === 'fulfilled') {
        const metrics = metricsResult.value;
        totalSubmissions = metrics.total_submissions ?? metrics.total;
        pendingReviews = metrics.pending_submissions ?? metrics.pending_review;
        approvedContent = metrics.approved_submissions ?? metrics.approved;
      } else {
        const reasonMsg = metricsResult.reason?.message || '';
        if (reasonMsg !== 'PERMISSION_DENIED_CONTENT') {
          submissionsError = metricsResult.reason?.message || 'Failed to fetch compliance metrics';
        }
      }

      // Check if both APIs failed with real network/server errors
      if (brandError && submissionsError) {
        setStatsError(`${brandError} & ${submissionsError}`);
      } else if (brandError && !canReadContent) {
        setStatsError(brandError);
      } else if (submissionsError && !canReadBrand) {
        setStatsError(submissionsError);
      }

      setStats({
        totalSubmissions,
        pendingReviews,
        approvedContent,
        activeBrandKits: activeKitsCount,
        hasPartialData: activeKitsCount !== null || totalSubmissions !== null,
        isSubmissionsCapped: isCapped,
        submissionsError,
        brandKitsError: brandError,
      });
      setStatsLastUpdated(new Date());
    } catch (err) {
      if (activeOrgRef.current === currentOrgId) {
        setStatsError(err instanceof Error ? err.message : 'Failed to load live dashboard stats');
      }
    } finally {
      if (activeOrgRef.current === currentOrgId) {
        setStatsLoading(false);
      }
    }
  }, [activeOrganisationId, canReadBrand, canReadContent]);

  useEffect(() => {
    void loadLiveStats();
  }, [loadLiveStats]);

  const handleFullRefresh = () => {
    refresh();
    void loadLiveStats();
  };

  const isStatsEmpty =
    stats !== null &&
    (stats.totalSubmissions === null || stats.totalSubmissions === 0) &&
    (stats.pendingReviews === null || stats.pendingReviews === 0) &&
    (stats.approvedContent === null || stats.approvedContent === 0) &&
    (stats.activeBrandKits === null || stats.activeBrandKits === 0) &&
    !statsLoading;

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Live System Telemetry Banner */}
      <section className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900/95 to-indigo-950/30 p-6 shadow-lg">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300">
              <ShieldCheck className="h-3.5 w-3.5 text-indigo-400" />
              <span>Phases 1–4 & 8 Live</span>
              <span>•</span>
              <span>Multi-Tenant Auth, Brand Hub & Compliance Online</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">
              Inkloom AI Live Telemetry & Compliance Operations
            </h2>
            <p className="text-sm text-slate-300 leading-relaxed">
              Every compliance finding and approval state in Inkloom AI is backed by persistent database
              records, cryptographically verified revisions, and organisation-isolated tenant rules.
            </p>
          </div>

          <button
            type="button"
            onClick={handleFullRefresh}
            disabled={loading || statsLoading}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow hover:bg-indigo-500 transition disabled:opacity-50"
            title="Refresh backend telemetry and live database metrics"
          >
            <RefreshCw className={`h-4 w-4 ${loading || statsLoading ? 'animate-spin' : ''}`} />
            <span>Refresh Dashboard</span>
          </button>
        </div>

        {/* Live System Health Cards */}
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>FastAPI Backend</span>
              <Server className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="mt-2 flex items-center gap-2">
              {isApiOnline ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
              ) : (
                <XCircle className="h-5 w-5 text-rose-400 shrink-0" />
              )}
              <span className="text-lg font-semibold text-white">
                {loading ? 'Probing...' : isApiOnline ? 'Connected' : 'Unreachable'}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400 truncate" title={getApiBaseUrl()}>
              Endpoint: {getApiBaseUrl()}/api/v1/health
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>PostgreSQL + pgvector</span>
              <Database className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="mt-2 flex items-center gap-2">
              {health?.database_connected ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
              ) : (
                <ShieldAlert className="h-5 w-5 text-amber-400 shrink-0" />
              )}
              <span className="text-lg font-semibold text-white">
                {health ? (health.database_connected ? 'Online' : 'Offline') : 'Unknown'}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400 truncate" title={health?.database_status}>
              Status: {health?.database_status ?? 'Awaiting API response'}
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Vector Index Spec</span>
              <Cpu className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="mt-2 text-lg font-semibold text-white">
              {health ? `${health.pgvector_target_dimension} Dimensions` : '1024 Dimensions'}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Model: BAAI/bge-large-en-v1.5
            </p>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Last Telemetry Probe</span>
              <Clock className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="mt-2 text-lg font-semibold text-white">
              {lastChecked ? lastChecked.toLocaleTimeString() : 'Pending'}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Env: {health?.environment ?? 'development'} (v{health?.version ?? '0.1.0'})
            </p>
          </div>
        </div>
      </section>

      {/* Live Operational Metrics Section */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-white">
                Live Organisation Telemetry & Content Metrics
              </h3>
              {statsLoading && (
                <span className="inline-flex items-center gap-1 text-xs text-indigo-400 animate-pulse">
                  <RefreshCw className="h-3 w-3 animate-spin" /> Fetching live counts...
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">
              Directly computed from persistent database records for your active organisation workspace.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {statsLastUpdated && (
              <span className="text-[11px] text-slate-500">
                Updated {statsLastUpdated.toLocaleTimeString()}
              </span>
            )}
            <span className="rounded-md bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 text-xs font-medium text-emerald-300">
              Tenant-Isolated DB Records
            </span>
          </div>
        </div>

        {/* Error Notification */}
        {statsError && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{statsError}</span>
            </div>
            <button
              type="button"
              onClick={() => void loadLiveStats()}
              className="text-xs underline hover:text-rose-200 transition"
            >
              Retry
            </button>
          </div>
        )}

        {/* Live Metrics Grid with Skeleton Loaders and Per-Metric RBAC States */}
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Card 1: Total Submissions */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 flex flex-col justify-between hover:border-slate-700/80 transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Total Submissions
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                <FileCheck2 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-slate-800" />
              ) : !canReadContent ? (
                <div className="flex items-center gap-1.5 text-xs text-slate-500 py-2">
                  <Lock className="h-3.5 w-3.5 text-slate-400" />
                  <span>Requires content:review</span>
                </div>
              ) : (
                <div className="text-3xl font-bold tracking-tight text-white flex items-baseline gap-1.5">
                  <span>{stats?.totalSubmissions ?? '—'}</span>
                  {stats?.isSubmissionsCapped && (
                    <span className="text-xs font-normal text-slate-500" title="Capped at latest 200 records in current API">
                      (latest 200)
                    </span>
                  )}
                </div>
              )}
              <p className="mt-1 text-xs text-slate-400">
                All marketing & copy submissions evaluated
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              {canReadContent ? (
                <Link
                  to="/compliance-review"
                  className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 font-medium"
                >
                  <span>View Workbench</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-slate-600">Restricted role</span>
              )}
            </div>
          </div>

          {/* Card 2: Pending Reviews */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 flex flex-col justify-between hover:border-slate-700/80 transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Pending Reviews
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
                <Clock4 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-slate-800" />
              ) : !canReadContent ? (
                <div className="flex items-center gap-1.5 text-xs text-slate-500 py-2">
                  <Lock className="h-3.5 w-3.5 text-slate-400" />
                  <span>Requires content:review</span>
                </div>
              ) : (
                <div className="text-3xl font-bold tracking-tight text-white flex items-center gap-2">
                  <span>{stats?.pendingReviews ?? '—'}</span>
                  {stats && stats.pendingReviews !== null && stats.pendingReviews > 0 && (
                    <span className="text-xs font-medium text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5">
                      Needs Action
                    </span>
                  )}
                </div>
              )}
              <p className="mt-1 text-xs text-slate-400">
                Submissions awaiting human reviewer approval
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              {canReadContent ? (
                <Link
                  to="/compliance-review"
                  className="inline-flex items-center gap-1 text-amber-400 hover:text-amber-300 font-medium"
                >
                  <span>Review Submissions</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-slate-600">Restricted role</span>
              )}
            </div>
          </div>

          {/* Card 3: Approved Content */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 flex flex-col justify-between hover:border-slate-700/80 transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Approved Content
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Award className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-slate-800" />
              ) : !canReadContent ? (
                <div className="flex items-center gap-1.5 text-xs text-slate-500 py-2">
                  <Lock className="h-3.5 w-3.5 text-slate-400" />
                  <span>Requires content:review</span>
                </div>
              ) : (
                <div className="text-3xl font-bold tracking-tight text-white">
                  {stats?.approvedContent ?? '—'}
                </div>
              )}
              <p className="mt-1 text-xs text-slate-400">
                Revisions approved by authorized reviewer
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              {canReadContent ? (
                <Link
                  to="/compliance-review"
                  className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300 font-medium"
                >
                  <span>Filter Approved</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-slate-600">Restricted role</span>
              )}
            </div>
          </div>

          {/* Card 4: Active Brand Kits */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 flex flex-col justify-between hover:border-slate-700/80 transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Active Brand Kits
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/10 text-purple-400 border border-purple-500/20">
                <BookOpen className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-slate-800" />
              ) : !canReadBrand ? (
                <div className="flex items-center gap-1.5 text-xs text-slate-500 py-2">
                  <Lock className="h-3.5 w-3.5 text-slate-400" />
                  <span>Requires brand:read</span>
                </div>
              ) : (
                <div className="text-3xl font-bold tracking-tight text-white">
                  {stats?.activeBrandKits ?? '—'}
                </div>
              )}
              <p className="mt-1 text-xs text-slate-400">
                Configured brand kits with active versions
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              {canReadBrand ? (
                <Link
                  to="/brand-hub"
                  className="inline-flex items-center gap-1 text-purple-400 hover:text-purple-300 font-medium"
                >
                  <span>Manage Brand Kits</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-slate-600">Restricted role</span>
              )}
            </div>
          </div>
        </div>

        {/* Empty State Banner when no content or kits have been created */}
        {isStatsEmpty && !statsLoading && (
          <div className="mt-6 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-6 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-indigo-500/10 text-indigo-400">
              <BookOpen className="h-6 w-6" />
            </div>
            <h4 className="mt-3 text-sm font-semibold text-white">Workspace Initialized — No Data Yet</h4>
            <p className="mt-1 text-xs text-slate-400 max-w-md mx-auto">
              Get started by creating your first Brand Kit in Brand Hub, or submit copy to run automated
              compliance checks against versioned rules.
            </p>
            <div className="mt-4 flex items-center justify-center gap-3">
              <Link
                to="/brand-hub"
                className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 transition"
              >
                Create Brand Kit
              </Link>
              <Link
                to="/compliance-review"
                className="rounded-lg border border-slate-700 bg-slate-800 px-3.5 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-700 transition"
              >
                Submit Content
              </Link>
            </div>
          </div>
        )}
      </section>

      {/* Module Implementation Status & Team Ownership */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white flex items-center gap-2">
              <Layers className="h-5 w-5 text-indigo-400" />
              <span>Phased Architecture & Module Status</span>
            </h3>
            <p className="text-xs text-slate-400">
              Clear separation between implemented platform modules and planned upcoming phases.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {MODULE_ROADMAP.map((mod) => {
            const isImplemented = mod.status === 'implemented';
            return (
              <div
                key={mod.id}
                className={`rounded-xl border p-5 flex flex-col justify-between transition ${
                  isImplemented
                    ? 'border-emerald-500/40 bg-emerald-950/10'
                    : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                      Phase {mod.phase}
                    </span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                        isImplemented
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-slate-800 text-slate-400 border border-slate-700'
                      }`}
                    >
                      {isImplemented ? 'Implemented' : 'Planned'}
                    </span>
                  </div>
                  <h4 className="mt-2 text-base font-semibold text-white">{mod.name}</h4>
                  <p className="mt-1 text-xs text-slate-400 leading-relaxed">{mod.description}</p>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
                  <span className="text-slate-500">Owner: {mod.owner}</span>
                  {mod.route !== '/' && (
                    <Link
                      to={mod.route}
                      className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 font-medium"
                    >
                      <span>Inspect</span>
                      <ArrowRight className="h-3 w-3" />
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
};
