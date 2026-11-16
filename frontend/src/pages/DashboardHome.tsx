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
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      {/* Live System Telemetry Banner - Minimal ChatGPT Dark Surface */}
      <section className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#10A37F]/30 bg-[#10A37F]/10 px-3 py-0.5 text-xs font-medium text-[#10A37F]">
              <ShieldCheck className="h-3.5 w-3.5 text-[#10A37F] shrink-0" />
              <span>Phases 1–4 & 8 Live</span>
              <span className="text-[#10A37F]/50">•</span>
              <span>Multi-Tenant Auth, Brand Hub & Compliance Online</span>
            </div>
            <h2 className="text-xl font-semibold text-[#ECECEC] tracking-tight">
              Inkloom AI Live Telemetry & Compliance Operations
            </h2>
            <p className="text-xs text-[#A1A1AA] leading-relaxed">
              Every compliance finding and approval state in Inkloom AI is backed by persistent database
              records, cryptographically verified revisions, and organisation-isolated tenant rules.
            </p>
          </div>

          <button
            type="button"
            onClick={handleFullRefresh}
            disabled={loading || statsLoading}
            className="inline-flex items-center gap-2 rounded-lg bg-[#10A37F] hover:bg-[#0D8F70] px-4 py-2 text-xs font-semibold text-white transition disabled:opacity-50"
            title="Refresh backend telemetry and live database metrics"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading || statsLoading ? 'animate-spin' : ''}`} />
            <span>Refresh Dashboard</span>
          </button>
        </div>

        {/* Live System Health Cards */}
        <div className="mt-5 grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 transition hover:border-[#71717A]">
            <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
              <span className="uppercase tracking-wider text-[10px]">FastAPI Backend</span>
              <Server className="h-3.5 w-3.5 text-[#A1A1AA]" />
            </div>
            <div className="mt-2 flex items-center gap-2">
              {isApiOnline ? (
                <CheckCircle2 className="h-4 w-4 text-[#10A37F] shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 text-[#EF4444] shrink-0" />
              )}
              <span className="text-sm font-semibold text-[#ECECEC]">
                {loading ? 'Probing...' : isApiOnline ? 'Connected' : 'Unreachable'}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-[#71717A] font-mono truncate" title={getApiBaseUrl()}>
              {getApiBaseUrl()}/api/v1/health
            </p>
          </div>

          <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 transition hover:border-[#71717A]">
            <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
              <span className="uppercase tracking-wider text-[10px]">PostgreSQL + pgvector</span>
              <Database className="h-3.5 w-3.5 text-[#A1A1AA]" />
            </div>
            <div className="mt-2 flex items-center gap-2">
              {health?.database_connected ? (
                <CheckCircle2 className="h-4 w-4 text-[#10A37F] shrink-0" />
              ) : (
                <ShieldAlert className="h-4 w-4 text-[#F59E0B] shrink-0" />
              )}
              <span className="text-sm font-semibold text-[#ECECEC]">
                {health ? (health.database_connected ? 'Online' : 'Offline') : 'Unknown'}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-[#71717A] font-mono truncate" title={health?.database_status}>
              Status: {health?.database_status ?? 'Awaiting API response'}
            </p>
          </div>

          <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 transition hover:border-[#71717A]">
            <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
              <span className="uppercase tracking-wider text-[10px]">Vector Index Spec</span>
              <Cpu className="h-3.5 w-3.5 text-[#A1A1AA]" />
            </div>
            <div className="mt-2 text-sm font-semibold text-[#ECECEC]">
              {health ? `${health.pgvector_target_dimension} Dimensions` : '1024 Dimensions'}
            </div>
            <p className="mt-1 text-[11px] text-[#71717A] font-mono truncate">
              BAAI/bge-large-en-v1.5
            </p>
          </div>

          <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 transition hover:border-[#71717A]">
            <div className="flex items-center justify-between text-xs text-[#A1A1AA]">
              <span className="uppercase tracking-wider text-[10px]">Last Telemetry Probe</span>
              <Clock className="h-3.5 w-3.5 text-[#A1A1AA]" />
            </div>
            <div className="mt-2 text-sm font-semibold text-[#ECECEC]">
              {lastChecked ? lastChecked.toLocaleTimeString() : 'Pending'}
            </div>
            <p className="mt-1 text-[11px] text-[#71717A] font-mono truncate">
              {health?.environment ?? 'dev'} (v{health?.version ?? '0.1.0'})
            </p>
          </div>
        </div>
      </section>

      {/* Live Operational Metrics Section */}
      <section className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#424242] pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-[#ECECEC]">
                Live Organisation Telemetry & Content Metrics
              </h3>
              {statsLoading && (
                <span className="inline-flex items-center gap-1 text-xs text-[#10A37F] animate-pulse bg-[#10A37F]/10 px-2 py-0.5 rounded border border-[#10A37F]/20">
                  <RefreshCw className="h-3 w-3 animate-spin" /> Fetching counts...
                </span>
              )}
            </div>
            <p className="text-xs text-[#A1A1AA] mt-0.5">
              Directly computed from persistent database records for your active organisation workspace.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {statsLastUpdated && (
              <span className="text-xs text-[#71717A]">
                Updated {statsLastUpdated.toLocaleTimeString()}
              </span>
            )}
            <span className="rounded bg-[#212121] border border-[#424242] px-2.5 py-0.5 text-xs text-[#A1A1AA]">
              Tenant-Isolated DB Records
            </span>
          </div>
        </div>

        {/* Error Notification */}
        {statsError && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-3 text-xs text-[#EF4444]">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{statsError}</span>
            </div>
            <button
              type="button"
              onClick={() => void loadLiveStats()}
              className="text-xs font-medium underline hover:text-[#ECECEC] transition"
            >
              Retry
            </button>
          </div>
        )}

        {/* Live Metrics Grid */}
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Card 1: Total Submissions */}
          <div className="rounded-lg border border-[#424242] bg-[#212121] p-4 flex flex-col justify-between hover:border-[#71717A] transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#A1A1AA] uppercase tracking-wider">
                Total Submissions
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded bg-[#2F2F2F] text-[#ECECEC] border border-[#424242]">
                <FileCheck2 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-[#2F2F2F]" />
              ) : !canReadContent ? (
                <div className="flex items-center gap-1.5 text-xs text-[#71717A] py-2">
                  <Lock className="h-3.5 w-3.5 text-[#71717A]" />
                  <span>Requires content:review</span>
                </div>
              ) : (
                <div className="text-2xl font-bold tracking-tight text-[#ECECEC] flex items-baseline gap-1.5">
                  <span>{stats?.totalSubmissions ?? '—'}</span>
                  {stats?.isSubmissionsCapped && (
                    <span className="text-xs font-normal text-[#71717A]" title="Capped at latest 200 records in current API">
                      (latest 200)
                    </span>
                  )}
                </div>
              )}
              <p className="mt-1 text-xs text-[#71717A]">
                All marketing & copy submissions evaluated
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-[#424242] flex items-center justify-between text-xs">
              {canReadContent ? (
                <Link
                  to="/compliance-review"
                  className="inline-flex items-center gap-1 text-[#10A37F] hover:underline font-medium"
                >
                  <span>View Workbench</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-[#71717A]">Restricted role</span>
              )}
            </div>
          </div>

          {/* Card 2: Pending Reviews */}
          <div className="rounded-lg border border-[#424242] bg-[#212121] p-4 flex flex-col justify-between hover:border-[#71717A] transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#A1A1AA] uppercase tracking-wider">
                Pending Reviews
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded bg-[#2F2F2F] text-[#F59E0B] border border-[#424242]">
                <Clock4 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-[#2F2F2F]" />
              ) : !canReadContent ? (
                <div className="flex items-center gap-1.5 text-xs text-[#71717A] py-2">
                  <Lock className="h-3.5 w-3.5 text-[#71717A]" />
                  <span>Requires content:review</span>
                </div>
              ) : (
                <div className="text-2xl font-bold tracking-tight text-[#ECECEC] flex items-center gap-2">
                  <span>{stats?.pendingReviews ?? '—'}</span>
                  {stats && stats.pendingReviews !== null && stats.pendingReviews > 0 && (
                    <span className="text-xs font-semibold text-[#F59E0B] bg-[#F59E0B]/15 border border-[#F59E0B]/30 rounded px-2 py-0.2">
                      Needs Action
                    </span>
                  )}
                </div>
              )}
              <p className="mt-1 text-xs text-[#71717A]">
                Submissions awaiting human reviewer approval
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-[#424242] flex items-center justify-between text-xs">
              {canReadContent ? (
                <Link
                  to="/approvals"
                  className="inline-flex items-center gap-1 text-[#F59E0B] hover:underline font-medium"
                >
                  <span>Review Submissions</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-[#71717A]">Restricted role</span>
              )}
            </div>
          </div>

          {/* Card 3: Approved Content */}
          <div className="rounded-lg border border-[#424242] bg-[#212121] p-4 flex flex-col justify-between hover:border-[#71717A] transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#A1A1AA] uppercase tracking-wider">
                Approved Content
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded bg-[#2F2F2F] text-[#10A37F] border border-[#424242]">
                <Award className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-[#2F2F2F]" />
              ) : !canReadContent ? (
                <div className="flex items-center gap-1.5 text-xs text-[#71717A] py-2">
                  <Lock className="h-3.5 w-3.5 text-[#71717A]" />
                  <span>Requires content:review</span>
                </div>
              ) : (
                <div className="text-2xl font-bold tracking-tight text-[#ECECEC]">
                  {stats?.approvedContent ?? '—'}
                </div>
              )}
              <p className="mt-1 text-xs text-[#71717A]">
                Revisions approved by authorized reviewer
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-[#424242] flex items-center justify-between text-xs">
              {canReadContent ? (
                <Link
                  to="/approvals"
                  className="inline-flex items-center gap-1 text-[#10A37F] hover:underline font-medium"
                >
                  <span>Filter Approved</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-[#71717A]">Restricted role</span>
              )}
            </div>
          </div>

          {/* Card 4: Active Brand Kits */}
          <div className="rounded-lg border border-[#424242] bg-[#212121] p-4 flex flex-col justify-between hover:border-[#71717A] transition">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[#A1A1AA] uppercase tracking-wider">
                Active Brand Kits
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded bg-[#2F2F2F] text-[#ECECEC] border border-[#424242]">
                <BookOpen className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              {statsLoading && !stats ? (
                <div className="h-8 w-20 animate-pulse rounded bg-[#2F2F2F]" />
              ) : !canReadBrand ? (
                <div className="flex items-center gap-1.5 text-xs text-[#71717A] py-2">
                  <Lock className="h-3.5 w-3.5 text-[#71717A]" />
                  <span>Requires brand:read</span>
                </div>
              ) : (
                <div className="text-2xl font-bold tracking-tight text-[#ECECEC]">
                  {stats?.activeBrandKits ?? '—'}
                </div>
              )}
              <p className="mt-1 text-xs text-[#71717A]">
                Configured brand kits with active versions
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-[#424242] flex items-center justify-between text-xs">
              {canReadBrand ? (
                <Link
                  to="/brand-hub"
                  className="inline-flex items-center gap-1 text-[#ECECEC] hover:text-[#10A37F] font-medium transition-colors"
                >
                  <span>Manage Brand Kits</span>
                  <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <span className="text-[11px] text-[#71717A]">Restricted role</span>
              )}
            </div>
          </div>
        </div>

        {/* Empty State Banner */}
        {isStatsEmpty && !statsLoading && (
          <div className="mt-6 rounded-lg border border-dashed border-[#424242] bg-[#212121] p-6 text-center">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg bg-[#2F2F2F] text-[#A1A1AA]">
              <BookOpen className="h-5 w-5" />
            </div>
            <h4 className="mt-3 text-sm font-semibold text-[#ECECEC]">Workspace Initialized — No Data Yet</h4>
            <p className="mt-1 text-xs text-[#A1A1AA] max-w-md mx-auto">
              Get started by creating your first Brand Kit in Brand Hub, or submit copy to run automated
              compliance checks against versioned rules.
            </p>
            <div className="mt-4 flex items-center justify-center gap-3">
              <Link
                to="/brand-hub"
                className="rounded-lg bg-[#10A37F] hover:bg-[#0D8F70] px-3.5 py-1.5 text-xs font-semibold text-white transition"
              >
                Create Brand Kit
              </Link>
              <Link
                to="/compliance-review"
                className="rounded-lg border border-[#424242] bg-[#2F2F2F] hover:bg-[#424242] px-3.5 py-1.5 text-xs font-semibold text-[#ECECEC] transition"
              >
                Submit Content
              </Link>
            </div>
          </div>
        )}
      </section>

      {/* Module Implementation Status */}
      <section className="space-y-4">
        <div>
          <h3 className="text-base font-semibold text-[#ECECEC] flex items-center gap-2">
            <Layers className="h-4 w-4 text-[#10A37F]" />
            <span>Phased Architecture & Module Status</span>
          </h3>
          <p className="text-xs text-[#A1A1AA]">
            Clear separation between implemented platform modules and planned upcoming phases.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {MODULE_ROADMAP.map((mod) => {
            const isImplemented = mod.status === 'implemented';
            return (
              <div
                key={mod.id}
                className="rounded-lg border border-[#424242] bg-[#2F2F2F] p-4 flex flex-col justify-between hover:border-[#71717A] transition"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-mono uppercase tracking-wider text-[#A1A1AA]">
                      Phase {mod.phase}
                    </span>
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                        isImplemented
                          ? 'bg-[#10A37F]/15 text-[#10A37F] border border-[#10A37F]/30'
                          : 'bg-[#212121] text-[#71717A] border border-[#424242]'
                      }`}
                    >
                      {isImplemented ? 'Implemented' : 'Planned'}
                    </span>
                  </div>
                  <h4 className="mt-2 text-sm font-semibold text-[#ECECEC]">{mod.name}</h4>
                  <p className="mt-1 text-xs text-[#A1A1AA] leading-relaxed">{mod.description}</p>
                </div>

                <div className="mt-4 pt-3 border-t border-[#424242] flex items-center justify-between text-xs">
                  <span className="text-[#71717A]">Owner: {mod.owner}</span>
                  {mod.route !== '/' && (
                    <Link
                      to={mod.route}
                      className="inline-flex items-center gap-1 text-[#10A37F] hover:underline font-medium"
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

export default DashboardHome;
