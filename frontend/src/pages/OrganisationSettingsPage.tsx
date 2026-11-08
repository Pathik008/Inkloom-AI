import React, { useCallback, useEffect, useState } from 'react';
import {
  Building2,
  Users,
  Shield,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  KeyRound,
  Mail,
  Copy,
  Check,
  Clock,
  Ban,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import {
  InvitationCreateResponse,
  OrganisationDetail,
  OrganisationInvitation,
  OrganisationMember,
  RoleName,
} from '../types';
import {
  createOrganisation,
  createOrganisationInvitation,
  getOrganisationDetails,
  listOrganisationInvitations,
  listOrganisationMembers,
  removeOrganisationMember,
  revokeOrganisationInvitation,
  updateOrganisationDetails,
  updateOrganisationMemberRole,
} from '../services/api';

const AVAILABLE_ROLES: RoleName[] = ['ADMIN', 'BRAND_MANAGER', 'CONTENT_CREATOR', 'REVIEWER'];

export const OrganisationSettingsPage: React.FC = () => {
  const {
    user,
    activeOrganisationId,
    activeRole,
    activePermissions,
    hasPermission,
    switchOrganisation,
    refreshUser,
  } = useAuth();

  const [orgDetail, setOrgDetail] = useState<OrganisationDetail | null>(null);
  const [members, setMembers] = useState<OrganisationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganisationInvitation[]>([]);
  const [loadingData, setLoadingData] = useState<boolean>(true);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Edit current organisation state
  const [editOrgName, setEditOrgName] = useState('');
  const [editOrgDesc, setEditOrgDesc] = useState('');
  const [savingOrg, setSavingOrg] = useState(false);

  // Create new organisation state
  const [newOrgName, setNewOrgName] = useState('');
  const [newOrgDesc, setNewOrgDesc] = useState('');
  const [creatingOrg, setCreatingOrg] = useState(false);

  // Team invitation state
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<RoleName>('CONTENT_CREATOR');
  const [sendingInvite, setSendingInvite] = useState(false);
  const [createdInvitation, setCreatedInvitation] = useState<InvitationCreateResponse | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const loadWorkspaceData = useCallback(async () => {
    if (!activeOrganisationId) {
      setLoadingData(false);
      return;
    }
    setLoadingData(true);
    try {
      const [detail, memberList, invitationList] = await Promise.all([
        getOrganisationDetails(activeOrganisationId),
        listOrganisationMembers(activeOrganisationId),
        listOrganisationInvitations(activeOrganisationId).catch(() => [] as OrganisationInvitation[]),
      ]);
      setOrgDetail(detail);
      setEditOrgName(detail.name);
      setEditOrgDesc(detail.description || '');
      setMembers(memberList);
      setInvitations(invitationList);
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to load organisation settings.',
      });
    } finally {
      setLoadingData(false);
    }
  }, [activeOrganisationId]);

  useEffect(() => {
    void loadWorkspaceData();
  }, [loadWorkspaceData]);

  const handleUpdateOrganisation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrganisationId) return;
    setSavingOrg(true);
    setFeedback(null);
    try {
      const updated = await updateOrganisationDetails(activeOrganisationId, {
        name: editOrgName.trim(),
        description: editOrgDesc.trim() || null,
      });
      setOrgDetail(updated);
      await refreshUser();
      setFeedback({ type: 'success', message: 'Organisation profile updated.' });
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to update organisation.',
      });
    } finally {
      setSavingOrg(false);
    }
  };

  const handleCreateOrganisation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newOrgName.trim().length < 2) return;
    setCreatingOrg(true);
    setFeedback(null);
    try {
      const created = await createOrganisation({
        name: newOrgName.trim(),
        description: newOrgDesc.trim() || undefined,
      });
      setNewOrgName('');
      setNewOrgDesc('');
      await switchOrganisation(created.id);
      setFeedback({
        type: 'success',
        message: `Created and switched to workspace "${created.name}".`,
      });
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to create organisation.',
      });
    } finally {
      setCreatingOrg(false);
    }
  };

  const handleSendInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrganisationId || !inviteEmail.trim()) return;
    setSendingInvite(true);
    setFeedback(null);
    setCreatedInvitation(null);
    setCopiedToken(false);
    try {
      const resp = await createOrganisationInvitation(activeOrganisationId, {
        email: inviteEmail.trim().toLowerCase(),
        role: inviteRole,
      });
      setInviteEmail('');
      setCreatedInvitation(resp);
      await loadWorkspaceData();
      setFeedback({
        type: 'success',
        message: `Invitation generated for ${resp.email}. Share the invitation link to complete onboarding.`,
      });
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to send invitation.',
      });
    } finally {
      setSendingInvite(false);
    }
  };

  const handleRevokeInvitation = async (invitationId: string, email: string) => {
    if (!activeOrganisationId) return;
    if (!window.confirm(`Revoke invitation for ${email}? They will no longer be able to use the link.`)) return;
    setRevokingId(invitationId);
    setFeedback(null);
    try {
      await revokeOrganisationInvitation(activeOrganisationId, invitationId);
      await loadWorkspaceData();
      setFeedback({ type: 'success', message: `Revoked invitation for ${email}.` });
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to revoke invitation.',
      });
    } finally {
      setRevokingId(null);
    }
  };

  const handleCopyInvitationLink = async () => {
    if (!createdInvitation) return;
    const fullUrl = `${window.location.origin}${createdInvitation.invitation_url}`;
    try {
      await navigator.clipboard.writeText(fullUrl);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2500);
    } catch {
      // Fallback if clipboard API not permitted
    }
  };

  const handleRoleChange = async (membershipId: string, newRole: RoleName) => {
    if (!activeOrganisationId) return;
    setFeedback(null);
    try {
      await updateOrganisationMemberRole(activeOrganisationId, membershipId, newRole);
      await loadWorkspaceData();
      await refreshUser();
      setFeedback({ type: 'success', message: `Updated member role to ${newRole}.` });
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to update member role.',
      });
    }
  };

  const handleRemoveMember = async (membershipId: string, email: string) => {
    if (!activeOrganisationId) return;
    if (!window.confirm(`Remove ${email} from this organisation workspace?`)) return;
    setFeedback(null);
    try {
      await removeOrganisationMember(activeOrganisationId, membershipId);
      await loadWorkspaceData();
      setFeedback({ type: 'success', message: `Removed ${email} from organisation.` });
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to remove member.',
      });
    }
  };

  const canManageOrg = hasPermission('organisation:manage');
  const canManageUsers = hasPermission('users:manage');

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight">
            Organisation Workspace & Multi-Tenant RBAC
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Manage organisation profile, switch tenant context, and enforce role-based access control.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-xl border border-indigo-500/30 bg-indigo-500/10 px-3.5 py-2 text-xs text-indigo-300">
          <Shield className="h-4 w-4" />
          <span>Active Role:</span>
          <strong className="font-mono text-white">{activeRole ?? 'NONE'}</strong>
        </div>
      </div>

      {feedback && (
        <div
          className={`rounded-xl border p-4 text-xs flex items-center gap-2.5 ${
            feedback.type === 'success'
              ? 'border-emerald-500/40 bg-emerald-950/20 text-emerald-200'
              : 'border-rose-500/40 bg-rose-950/20 text-rose-200'
          }`}
        >
          {feedback.type === 'success' ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          ) : (
            <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
          )}
          <span>{feedback.message}</span>
        </div>
      )}

      {/* Authenticated User & Permissions Card */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <KeyRound className="h-4 w-4 text-indigo-400" />
          <span>Authenticated User & Active Permission Grants</span>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 text-xs">
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5">
            <div className="text-slate-400">Full Name</div>
            <div className="mt-1 font-semibold text-white text-sm">{user?.full_name}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5">
            <div className="text-slate-400">Normalised Email</div>
            <div className="mt-1 font-mono text-white text-sm">{user?.email}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5">
            <div className="text-slate-400">Active Workspace Slug</div>
            <div className="mt-1 font-mono text-indigo-300 text-sm">{orgDetail?.slug ?? '—'}</div>
          </div>
        </div>

        <div>
          <div className="text-xs text-slate-400 mb-2">
            Effective Backend Permissions in Current Workspace:
          </div>
          <div className="flex flex-wrap gap-2">
            {activePermissions.map((perm) => (
              <span
                key={perm}
                className="rounded-md border border-indigo-500/30 bg-indigo-950/40 px-2.5 py-1 font-mono text-[11px] text-indigo-300"
              >
                {perm}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Organisation Profile & Create New Workspace */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Building2 className="h-4 w-4 text-indigo-400" />
              <span>Current Workspace Profile</span>
            </div>
            {!canManageOrg && (
              <span className="text-[11px] text-amber-400">Read-only (Requires organisation:manage)</span>
            )}
          </div>

          {loadingData ? (
            <div className="flex items-center gap-2 text-xs text-slate-400 py-6">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Loading organisation details...</span>
            </div>
          ) : (
            <form onSubmit={handleUpdateOrganisation} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Organisation Name
                </label>
                <input
                  type="text"
                  disabled={!canManageOrg || savingOrg}
                  value={editOrgName}
                  onChange={(e) => setEditOrgName(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-sm text-white disabled:opacity-60"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Description
                </label>
                <input
                  type="text"
                  disabled={!canManageOrg || savingOrg}
                  value={editOrgDesc}
                  onChange={(e) => setEditOrgDesc(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-sm text-white disabled:opacity-60"
                />
              </div>

              {canManageOrg && (
                <button
                  type="submit"
                  disabled={savingOrg}
                  className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition disabled:opacity-50"
                >
                  {savingOrg ? 'Saving...' : 'Save Workspace Details'}
                </button>
              )}
            </form>
          )}
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Plus className="h-4 w-4 text-indigo-400" />
            <span>Create Additional Organisation Workspace</span>
          </div>
          <p className="text-xs text-slate-400">
            Users can belong to multiple isolated organisations. Creating a new workspace assigns you as its <code className="text-indigo-300">ADMIN</code>.
          </p>

          <form onSubmit={handleCreateOrganisation} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                New Workspace Name
              </label>
              <input
                type="text"
                required
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                placeholder="e.g., Horizon Retail India"
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-sm text-white"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Description (Optional)
              </label>
              <input
                type="text"
                value={newOrgDesc}
                onChange={(e) => setNewOrgDesc(e.target.value)}
                placeholder="Regional brand compliance division"
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-sm text-white"
              />
            </div>

            <button
              type="submit"
              disabled={creatingOrg}
              className="inline-flex items-center gap-2 rounded-xl border border-indigo-500/40 bg-indigo-600/20 px-4 py-2 text-xs font-semibold text-indigo-200 hover:bg-indigo-600 hover:text-white transition disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>{creatingOrg ? 'Creating...' : 'Create & Switch Workspace'}</span>
            </button>
          </form>
        </section>
      </div>

      {/* Organisation Members & Role Assignment */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Users className="h-4 w-4 text-indigo-400" />
            <span>Organisation Members ({members.length})</span>
          </div>
          <span className="text-xs text-slate-400">
            Last active ADMIN is protected from removal or demotion
          </span>
        </div>

        {/* Freshly Generated Invitation Link Banner */}
        {createdInvitation && (
          <div className="rounded-2xl border border-indigo-500/40 bg-indigo-950/40 p-5 space-y-3">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Mail className="h-4 w-4 text-indigo-400" />
                <span>Invitation Ready to Share</span>
              </div>
              <button
                type="button"
                onClick={() => setCreatedInvitation(null)}
                className="text-xs text-slate-400 hover:text-slate-200 transition"
              >
                Dismiss
              </button>
            </div>
            <p className="text-xs text-slate-300">
              An invitation has been generated for{' '}
              <strong className="text-white font-mono">{createdInvitation.email}</strong> with role{' '}
              <span className="rounded bg-indigo-500/20 px-2 py-0.5 font-mono text-indigo-300">
                {createdInvitation.role}
              </span>
              . The secure invitation link contains a single-use cryptographic token. Share this link directly with the recipient:
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                readOnly
                value={`${window.location.origin}${createdInvitation.invitation_url}`}
                className="flex-1 min-w-[260px] rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 font-mono text-xs text-slate-200 select-all"
                onClick={(e) => (e.target as HTMLInputElement).select()}
              />
              <button
                type="button"
                onClick={handleCopyInvitationLink}
                className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition shadow"
              >
                {copiedToken ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-300" />
                    <span>Copied Link!</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    <span>Copy Link</span>
                  </>
                )}
              </button>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-amber-300/90">
              <Clock className="h-3.5 w-3.5 shrink-0" />
              <span>
                Token expires on {new Date(createdInvitation.expires_at).toLocaleString()}. The recipient will accept the invitation or set their password on this secure page.
              </span>
            </div>
          </div>
        )}

        {/* Invite Team Member Form */}
        {canManageUsers && (
          <form
            onSubmit={handleSendInvitation}
            className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-3"
          >
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <Mail className="h-3.5 w-3.5 text-indigo-400" />
              <span>Invite New Team Member</span>
            </div>
            <p className="text-[11px] text-slate-400">
              Invitations are delivered securely via a unique cryptographic token. The invitee can register a new account or accept with their existing account upon email verification. Direct member addition is disabled for security.
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="colleague@company.com"
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as RoleName)}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500 font-mono"
              >
                {AVAILABLE_ROLES.map((r) => (
                  <option key={r} value={r}>
                    Role: {r}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={sendingInvite}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition disabled:opacity-50"
              >
                {sendingInvite ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Generating Invitation...</span>
                  </>
                ) : (
                  <>
                    <Plus className="h-3.5 w-3.5" />
                    <span>Generate & Send Invitation</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}

        {/* Pending & Historical Invitations */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <Clock className="h-3.5 w-3.5 text-indigo-400" />
              <span>Pending & Historical Invitations ({invitations.length})</span>
            </div>
          </div>

          {invitations.length === 0 ? (
            <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-4 text-center text-xs text-slate-500">
              No pending or historical invitations for this workspace.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/50">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="py-2.5 px-3">Invitee Email</th>
                    <th className="py-2.5 px-3">Role</th>
                    <th className="py-2.5 px-3">Status</th>
                    <th className="py-2.5 px-3">Invited By</th>
                    <th className="py-2.5 px-3">Expires At</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {invitations.map((inv) => {
                    const isPending = inv.status === 'PENDING';
                    const statusColor =
                      inv.status === 'ACCEPTED'
                        ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-300'
                        : inv.status === 'PENDING'
                        ? 'bg-amber-500/20 border-amber-500/30 text-amber-300'
                        : inv.status === 'REVOKED'
                        ? 'bg-rose-500/20 border-rose-500/30 text-rose-300'
                        : 'bg-slate-700/30 border-slate-600/30 text-slate-400';

                    return (
                      <tr key={inv.id} className="hover:bg-slate-800/30">
                        <td className="py-2.5 px-3 font-mono text-slate-200">{inv.email}</td>
                        <td className="py-2.5 px-3">
                          <span className="rounded bg-indigo-500/20 px-2 py-0.5 font-mono text-[11px] text-indigo-300">
                            {inv.role}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusColor}`}
                          >
                            {inv.status}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-slate-400 text-[11px]">
                          {inv.invited_by?.full_name || inv.invited_by?.email || '—'}
                        </td>
                        <td className="py-2.5 px-3 text-slate-400 text-[11px]">
                          {new Date(inv.expires_at).toLocaleDateString()}
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          {isPending && canManageUsers && (
                            <button
                              type="button"
                              disabled={revokingId === inv.id}
                              onClick={() => void handleRevokeInvitation(inv.id, inv.email)}
                              className="inline-flex items-center gap-1 rounded border border-rose-500/30 bg-rose-950/30 px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-600 hover:text-white transition disabled:opacity-50"
                              title="Revoke invitation"
                            >
                              {revokingId === inv.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Ban className="h-3 w-3" />
                              )}
                              <span>Revoke</span>
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th className="py-3 px-3">Member</th>
                <th className="py-3 px-3">Email</th>
                <th className="py-3 px-3">Role</th>
                <th className="py-3 px-3">Status</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {members.map((m) => (
                <tr key={m.id} className="hover:bg-slate-800/30">
                  <td className="py-3 px-3 font-medium text-white">{m.user.full_name}</td>
                  <td className="py-3 px-3 font-mono text-slate-300">{m.user.email}</td>
                  <td className="py-3 px-3">
                    {canManageUsers ? (
                      <select
                        value={m.role}
                        onChange={(e) => void handleRoleChange(m.id, e.target.value as RoleName)}
                        className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-indigo-300 font-semibold"
                      >
                        {AVAILABLE_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="rounded bg-indigo-500/20 px-2 py-0.5 font-mono text-indigo-300">
                        {m.role}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-3">
                    <span className="rounded-full bg-emerald-500/20 border border-emerald-500/30 px-2 py-0.5 text-[10px] text-emerald-300">
                      {m.status}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-right">
                    {canManageUsers && (
                      <button
                        type="button"
                        onClick={() => void handleRemoveMember(m.id, m.user.email)}
                        className="inline-flex items-center gap-1 rounded border border-rose-500/30 bg-rose-950/30 px-2 py-1 text-rose-300 hover:bg-rose-600 hover:text-white transition"
                        title="Remove member"
                      >
                        <Trash2 className="h-3 w-3" />
                        <span>Remove</span>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};
