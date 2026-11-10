import React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  ShieldCheck,
  LayoutDashboard,
  BookOpen,
  FileUp,
  FileCheck2,
  FileEdit,
  CheckSquare,
  BarChart3,
  ScrollText,
  Settings,
  LogOut,
  Building2,
} from 'lucide-react';
import { BackendStatusBadge } from '../components/BackendStatusBadge';
import { useBackendHealth } from '../hooks/useBackendHealth';
import { useAuth } from '../hooks/useAuth';

const NAV_ITEMS = [
  { to: '/', label: 'Overview & Telemetry', icon: LayoutDashboard, phase: 'Phase 1', requiredPermission: undefined },
  { to: '/settings', label: 'Org & RBAC Settings', icon: Settings, phase: 'Phase 2', requiredPermission: 'users:read' },
  { to: '/brand-hub', label: 'Brand Hub & Kits', icon: BookOpen, phase: 'Phase 3', requiredPermission: 'brand:read' },
  { to: '/content-upload', label: 'Content Ingestion', icon: FileUp, phase: 'Phase 4', requiredPermission: 'content:create' },
  { to: '/compliance-review', label: 'Compliance Review', icon: FileCheck2, phase: 'Phase 5-7', requiredPermission: 'content:review' },
  { to: '/content-editor', label: 'Content Editor', icon: FileEdit, phase: 'Phase 7', requiredPermission: 'content:edit' },
  { to: '/approvals', label: 'Approval Inbox', icon: CheckSquare, phase: 'Phase 8', requiredPermission: 'content:review' },
  { to: '/audit-logs', label: 'Audit Trail', icon: ScrollText, phase: 'Phase 8', requiredPermission: 'audit:read' },
  { to: '/analytics', label: 'Analytics & Reports', icon: BarChart3, phase: 'Phase 9', requiredPermission: 'content:review' },
];

export const AppLayout: React.FC = () => {
  const { health, loading, error, lastChecked, refresh } = useBackendHealth();
  const {
    user,
    activeOrganisationId,
    activeRole,
    hasPermission,
    switchOrganisation,
    logout,
  } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100">
      {/* Sidebar */}
      <aside className="w-72 border-r border-slate-800/80 bg-slate-900/60 flex flex-col justify-between shrink-0">
        <div>
          <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-800/80">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600/20 border border-indigo-500/40 text-indigo-400">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold tracking-tight text-white text-lg">Inkloom AI</span>
                <span className="rounded bg-indigo-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-indigo-300 border border-indigo-500/30">
                  Phase 2
                </span>
              </div>
              <p className="text-xs text-slate-400">Brand Compliance Platform</p>
            </div>
          </div>

          {/* Active Organisation Switcher */}
          {user && user.memberships.length > 0 && (
            <div className="px-4 py-3 border-b border-slate-800/80 bg-slate-950/40 space-y-1.5">
              <label
                htmlFor="org-switcher"
                className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400"
              >
                <Building2 className="h-3.5 w-3.5 text-indigo-400" />
                <span>Organisation Workspace</span>
              </label>
              <select
                id="org-switcher"
                value={activeOrganisationId ?? ''}
                onChange={(e) => void switchOrganisation(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white focus:border-indigo-500 focus:outline-none"
              >
                {user.memberships.map((m) => (
                  <option key={m.organisation.id} value={m.organisation.id}>
                    {m.organisation.name} ({m.role})
                  </option>
                ))}
              </select>
            </div>
          )}

          <nav className="p-3 space-y-1">
            {NAV_ITEMS.filter(
              (item) => !item.requiredPermission || hasPermission(item.requiredPermission),
            ).map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `flex items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium transition ${isActive
                      ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
                      : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200 border border-transparent'
                    }`
                  }
                >
                  <span className="flex items-center gap-3">
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{item.label}</span>
                  </span>
                  <span className="text-[10px] rounded px-1.5 py-0.5 bg-slate-800 text-slate-400">
                    {item.phase}
                  </span>
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* User Profile & Logout Footer */}
        <div className="p-4 border-t border-slate-800/80 bg-slate-950/40 space-y-3">
          {user && (
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="text-xs font-semibold text-white truncate">{user.full_name}</div>
                <div className="text-[11px] text-slate-400 truncate">{user.email}</div>
              </div>
              <span className="rounded bg-indigo-500/20 border border-indigo-500/30 px-2 py-0.5 text-[10px] font-mono font-semibold text-indigo-300 shrink-0">
                {activeRole}
              </span>
            </div>
          )}

          <button
            type="button"
            onClick={() => void handleLogout()}
            className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-200 hover:border-rose-500/50 hover:bg-rose-950/30 hover:text-rose-200 transition"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>Sign Out (Revoke Token)</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-800/80 bg-slate-900/40 px-8 py-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-white">
              Enterprise Brand Compliance & Marketing Review Workspace
            </h1>
            <p className="text-xs text-slate-400">
              Multi-Tenant RBAC • Deterministic Rule Validation • RAG Semantic Analysis • SHA-256 Approval Gate
            </p>
          </div>

          <BackendStatusBadge
            health={health}
            loading={loading}
            error={error}
            lastChecked={lastChecked}
            onRefresh={refresh}
          />
        </header>

        <main className="flex-1 p-8 overflow-y-auto">
          <Outlet context={{ health, loading, error, lastChecked, refresh }} />
        </main>
      </div>
    </div>
  );
};
