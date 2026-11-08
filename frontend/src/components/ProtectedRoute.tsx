import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { ShieldAlert, Loader2 } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredPermission?: string;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredPermission,
}) => {
  const { user, loading, activeRole, hasPermission } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-300">
        <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/80 px-6 py-4">
          <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
          <span className="text-sm font-medium">Verifying authenticated session...</span>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredPermission && !hasPermission(requiredPermission)) {
    return (
      <div className="max-w-2xl mx-auto mt-12 rounded-2xl border border-rose-500/30 bg-rose-950/10 p-8 text-slate-200 space-y-4">
        <div className="flex items-center gap-3 text-rose-400">
          <ShieldAlert className="h-6 w-6 shrink-0" />
          <h2 className="text-lg font-bold">Insufficient Role Permissions</h2>
        </div>
        <p className="text-sm text-slate-300 leading-relaxed">
          Your active role (<span className="font-mono font-semibold text-white">{activeRole}</span>)
          does not include the required <code className="text-rose-300">{requiredPermission}</code>{' '}
          permission in the selected organisation workspace.
        </p>
      </div>
    );
  }

  return <>{children}</>;
};
