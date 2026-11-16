import React from 'react';
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
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
  ChevronRight,
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
  const location = useLocation();

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const currentNav = NAV_ITEMS.find((item) =>
    item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to),
  );

  return (
    <div className="min-h-screen flex bg-[#212121] text-[#ECECEC] antialiased selection:bg-[#10A37F]/30">
      {/* Sidebar - ChatGPT Style Dark Sidebar (#171717) */}
      <aside className="w-64 border-r border-[#424242] bg-[#171717] flex flex-col justify-between shrink-0 z-20">
        <div className="flex flex-col min-h-0 flex-1">
          {/* Brand Header */}
          <div className="flex items-center gap-3 px-5 py-4 border-b border-[#424242]">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#2F2F2F] border border-[#424242] text-[#10A37F] shrink-0">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-semibold tracking-tight text-[#ECECEC] text-sm">Inkloom AI</span>
                <span className="rounded bg-[#10A37F]/15 px-1.5 py-0.2 text-[9px] font-semibold uppercase tracking-wider text-[#10A37F] border border-[#10A37F]/30">
                  Round 3
                </span>
              </div>
              <p className="text-[11px] text-[#A1A1AA] truncate">Brand Governance</p>
            </div>
          </div>

          {/* Active Organisation Switcher */}
          {user && user.memberships.length > 0 && (
            <div className="px-3.5 py-3 border-b border-[#424242] space-y-1">
              <label
                htmlFor="org-switcher"
                className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wider text-[#A1A1AA]"
              >
                <span className="flex items-center gap-1.5 text-[#A1A1AA]">
                  <Building2 className="h-3 w-3 text-[#10A37F]" />
                  <span>Workspace</span>
                </span>
                <span className="text-[9px] font-mono text-[#71717A]">Tenant</span>
              </label>
              <select
                id="org-switcher"
                value={activeOrganisationId ?? ''}
                onChange={(e) => void switchOrganisation(e.target.value)}
                className="w-full rounded-lg border border-[#424242] bg-[#212121] px-2.5 py-1.5 text-xs text-[#ECECEC] focus:border-[#10A37F] focus:outline-none transition cursor-pointer"
              >
                {user.memberships.map((m) => (
                  <option key={m.organisation.id} value={m.organisation.id}>
                    {m.organisation.name} • {m.role}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Navigation Links */}
          <nav className="p-2 space-y-0.5 overflow-y-auto flex-1">
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
                    `group flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                      isActive
                        ? 'bg-[#2F2F2F] text-[#ECECEC] font-semibold'
                        : 'text-[#A1A1AA] hover:bg-[#2F2F2F]/60 hover:text-[#ECECEC]'
                    }`
                  }
                >
                  <span className="flex items-center gap-2.5">
                    <Icon className="h-4 w-4 shrink-0 transition" />
                    <span>{item.label}</span>
                  </span>
                  <span className="text-[9px] rounded px-1.5 py-0.5 bg-[#212121] text-[#71717A] border border-[#424242] font-mono">
                    {item.phase}
                  </span>
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* User Profile & Logout Footer */}
        <div className="p-3 border-t border-[#424242] bg-[#171717] space-y-2">
          {user && (
            <div className="flex items-center justify-between gap-2 p-2 rounded-lg bg-[#212121] border border-[#424242]">
              <div className="flex items-center gap-2 min-w-0">
                <div className="h-7 w-7 rounded-md bg-[#10A37F]/20 text-[#10A37F] border border-[#10A37F]/30 flex items-center justify-center font-bold text-xs shrink-0">
                  {user.full_name?.charAt(0) || 'U'}
                </div>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-[#ECECEC] truncate">{user.full_name}</div>
                  <div className="text-[10px] text-[#A1A1AA] truncate">{user.email}</div>
                </div>
              </div>
              <span className="rounded bg-[#2F2F2F] border border-[#424242] px-1.5 py-0.5 text-[9px] font-mono text-[#A1A1AA] shrink-0">
                {activeRole}
              </span>
            </div>
          )}

          <button
            type="button"
            onClick={() => void handleLogout()}
            className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-[#424242] bg-[#212121] hover:bg-[#424242] px-3 py-1.5 text-xs font-medium text-[#A1A1AA] hover:text-[#ECECEC] transition"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#212121]">
        <header className="border-b border-[#424242] bg-[#212121] px-8 py-3.5 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-10">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 text-xs text-[#A1A1AA]">
              <span>Workspace</span>
              <ChevronRight className="h-3 w-3 text-[#71717A]" />
              <span className="font-medium text-[#ECECEC]">{currentNav?.label || 'Overview'}</span>
            </div>
            <h1 className="text-sm font-semibold text-[#ECECEC] tracking-tight">
              Enterprise Brand Compliance & Review Workspace
            </h1>
          </div>

          <div className="flex items-center gap-3">
            <BackendStatusBadge
              health={health}
              loading={loading}
              error={error}
              lastChecked={lastChecked}
              onRefresh={refresh}
            />
          </div>
        </header>

        <main className="flex-1 p-8 overflow-y-auto bg-[#212121]">
          <Outlet context={{ health, loading, error, lastChecked, refresh }} />
        </main>
      </div>
    </div>
  );
};

export default AppLayout;
