import React from 'react';
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
} from 'lucide-react';
import { HealthStatus } from '../types';
import { MODULE_ROADMAP } from '../utils/constants';
import { getApiBaseUrl } from '../services/api';

interface OutletContextType {
  health: HealthStatus | null;
  loading: boolean;
  error: string | null;
  lastChecked: Date | null;
  refresh: () => void;
}

export const DashboardHome: React.FC = () => {
  const { health, loading, error, lastChecked, refresh } = useOutletContext<OutletContextType>();
  const isApiOnline = Boolean(health && health.status === 'healthy' && !error);

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Live System Telemetry Banner */}
      <section className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 via-slate-900/95 to-indigo-950/30 p-6 shadow-lg">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300">
              <span>Phase 1 & Phase 2 Active</span>
              <span>•</span>
              <span>Multi-Tenant Auth & RBAC Online</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">
              Inkloom AI System Readiness & Architecture Shell
            </h2>
            <p className="text-sm text-slate-300 leading-relaxed">
              Every compliance finding in Inkloom AI must be traceable to an approved brand rule,
              versioned Brand Kit fact, or retrieved source document chunk. No fabricated compliance
              scores or placeholder analytics are displayed.
            </p>
          </div>

          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow hover:bg-indigo-500 transition disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            <span>Re-verify Backend Health</span>
          </button>
        </div>

        {/* Live Telemetry Cards */}
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

      {/* Honest Database Metrics Empty State (Phase 1 Rule Compliance) */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-white">
              Compliance & Review Telemetry (Database Records)
            </h3>
            <p className="text-xs text-slate-400">
              Strictly reflects real database records. No hardcoded or simulated compliance counters.
            </p>
          </div>
          <span className="rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 text-xs font-medium text-amber-300">
            Schema & Tenant Models Scheduled for Phase 2
          </span>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: 'Total Content Reviewed', state: 'Awaiting Phase 2-5 DB Schema' },
            { label: 'Approved Content Revisions', state: 'Awaiting Phase 8 Approval Gate' },
            { label: 'Pending Human Reviews', state: 'Awaiting Phase 8 Workflow' },
            { label: 'Critical / High Violations', state: 'Awaiting Phase 5-6 Engine' },
          ].map((metric) => (
            <div
              key={metric.label}
              className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-4"
            >
              <div className="text-xs text-slate-400">{metric.label}</div>
              <div className="mt-2 text-sm font-mono text-slate-500">Not initialized (Phase 1)</div>
              <div className="mt-1 text-[11px] text-slate-500">{metric.state}</div>
            </div>
          ))}
        </div>
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
              Clear separation between implemented Phase 1 foundation and planned Phase 2–10 modules.
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
