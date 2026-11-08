import React from 'react';
import { Activity, CheckCircle2, AlertTriangle, XCircle, RefreshCw, Database } from 'lucide-react';
import { HealthStatus } from '../types';

interface BackendStatusBadgeProps {
  health: HealthStatus | null;
  loading: boolean;
  error: string | null;
  lastChecked: Date | null;
  onRefresh: () => void;
}

export const BackendStatusBadge: React.FC<BackendStatusBadgeProps> = ({
  health,
  loading,
  error,
  lastChecked,
  onRefresh,
}) => {
  const isApiConnected = Boolean(health && health.status === 'healthy' && !error);
  const isDbConnected = Boolean(health?.database_connected);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/90 px-3.5 py-2 text-xs shadow-sm">
      <div className="flex items-center gap-2">
        {loading ? (
          <Activity className="h-4 w-4 animate-pulse text-indigo-400" />
        ) : isApiConnected ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        ) : (
          <XCircle className="h-4 w-4 text-rose-400" />
        )}
        <span className="font-medium text-slate-200">
          API:{' '}
          <span className={isApiConnected ? 'text-emerald-400' : 'text-rose-400'}>
            {loading ? 'Checking...' : isApiConnected ? `Connected (v${health?.version})` : 'Disconnected'}
          </span>
        </span>
      </div>

      <span className="text-slate-700">|</span>

      <div className="flex items-center gap-1.5">
        <Database className="h-3.5 w-3.5 text-slate-400" />
        <span className="text-slate-300">
          DB:{' '}
          {isApiConnected ? (
            <span className={isDbConnected ? 'text-emerald-400 font-medium' : 'text-amber-400 font-medium'}>
              {health?.database_status}
            </span>
          ) : (
            <span className="text-slate-500">Unknown</span>
          )}
        </span>
      </div>

      {error && (
        <span className="flex items-center gap-1 text-rose-400" title={error}>
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>{error}</span>
        </span>
      )}

      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        title={lastChecked ? `Last checked: ${lastChecked.toLocaleTimeString()}` : 'Check health now'}
        className="ml-1 inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200 transition hover:border-indigo-500 hover:text-white disabled:opacity-50"
      >
        <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
        <span>Probe</span>
      </button>
    </div>
  );
};
