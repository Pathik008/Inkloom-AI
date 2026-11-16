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
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#424242] bg-[#2F2F2F] px-3.5 py-1.5 text-xs shadow-sm">
      <div className="flex items-center gap-2">
        {loading ? (
          <Activity className="h-3.5 w-3.5 animate-pulse text-[#10A37F]" />
        ) : isApiConnected ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-[#10A37F]" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-[#EF4444]" />
        )}
        <span className="font-medium text-[#ECECEC]">
          API:{' '}
          <span className={isApiConnected ? 'text-[#10A37F]' : 'text-[#EF4444]'}>
            {loading ? 'Checking...' : isApiConnected ? `Connected (v${health?.version})` : 'Disconnected'}
          </span>
        </span>
      </div>

      <span className="text-[#424242]">|</span>

      <div className="flex items-center gap-1.5">
        <Database className="h-3.5 w-3.5 text-[#A1A1AA]" />
        <span className="text-[#A1A1AA]">
          DB:{' '}
          {isApiConnected ? (
            <span className={isDbConnected ? 'text-[#10A37F] font-medium' : 'text-[#F59E0B] font-medium'}>
              {health?.database_status}
            </span>
          ) : (
            <span className="text-[#71717A]">Unknown</span>
          )}
        </span>
      </div>

      {error && (
        <span className="flex items-center gap-1 text-[#EF4444]" title={error}>
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>{error}</span>
        </span>
      )}

      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        title={lastChecked ? `Last checked: ${lastChecked.toLocaleTimeString()}` : 'Check health now'}
        className="ml-1 inline-flex items-center gap-1 rounded-md border border-[#424242] bg-[#212121] px-2 py-1 text-[#ECECEC] transition hover:bg-[#424242] disabled:opacity-50"
      >
        <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
        <span>Probe</span>
      </button>
    </div>
  );
};
