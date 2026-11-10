import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Clock4,
  Eye,
  FileCheck2,
  FileText,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  UserCheck,
  X,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import {
  addReviewComment,
  fetchBrandKits,
  fetchContentSubmissions,
  fetchSubmissionDetail,
  submitApprovalDecision,
} from '../services/api';
import { BrandKitSummary, ContentSubmissionSummary } from '../types';

interface Finding {
  finding_id: string;
  rule_code: string;
  rule_title?: string;
  title?: string;
  severity: string;
  kind?: string;
  rule_type?: string;
  matched_text: string | null;
  start: number | null;
  end: number | null;
  evidence_excerpt: string | null;
  explanation: string;
  recommended_correction?: string;
  citation?: {
    chunk_id: string;
    document_id: string;
    document_title: string;
    page_number?: number | null;
    section_heading?: string | null;
    similarity_score?: number;
    content?: string;
  } | null;
  status?: string;
}

interface SubmissionDetail {
  id: string;
  organisation_id: string;
  brand_kit_id: string;
  brand_kit_version_id: string;
  parent_submission_id: string | null;
  revision_number: number;
  title: string;
  content_text: string;
  submitted_by_user_id: string | null;
  submitted_by_name: string | null;
  created_at: string;
  status: string;
  assigned_reviewer_id: string | null;
  assigned_reviewer_name: string | null;
  reviewed_by_user_id: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  reviewer_comments: string | null;
  analysis: {
    id: string;
    score: number;
    result: string;
    rules_evaluated: number;
    findings: Finding[];
    scoring: any;
    created_at: string;
  } | null;
  review_history: Array<{
    id: string;
    actor_name: string | null;
    action: string;
    comments: string | null;
    created_at: string;
  }>;
}

type FilterTab = 'ALL' | 'PENDING_REVIEW' | 'UNDER_REVIEW' | 'APPROVED' | 'REJECTED' | 'CHANGES_REQUESTED';

const SEV_BADGE: Record<string, string> = {
  CRITICAL: 'bg-rose-500/20 text-rose-300 border border-rose-500/40',
  HIGH: 'bg-orange-500/20 text-orange-300 border border-orange-500/40',
  MEDIUM: 'bg-amber-500/20 text-amber-300 border border-amber-500/40',
  LOW: 'bg-sky-500/20 text-sky-300 border border-sky-500/40',
  INFO: 'bg-slate-500/20 text-slate-300 border border-slate-500/40',
};

const STATUS_BADGE: Record<string, { label: string; badge: string }> = {
  PENDING_REVIEW: { label: 'Pending Review', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  UNDER_REVIEW: { label: 'Under Review', badge: 'bg-blue-500/15 text-blue-300 border-blue-500/30' },
  APPROVED: { label: 'Approved', badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  REJECTED: { label: 'Rejected', badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  CHANGES_REQUESTED: { label: 'Changes Requested', badge: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  DRAFT: { label: 'Draft', badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30' },
};

export const ApprovalsPage: React.FC = () => {
  const { user, activeOrganisationId, hasPermission } = useAuth();
  const canDecide = hasPermission('approval:decide');

  const [activeTab, setActiveTab] = useState<FilterTab>('ALL');
  const [submissions, setSubmissions] = useState<ContentSubmissionSummary[]>([]);
  const [brandKits, setBrandKits] = useState<BrandKitSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Selected submission modal / drawer state
  const [selectedSubId, setSelectedSubId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Review action modal state
  const [confirmAction, setConfirmAction] = useState<'APPROVE' | 'REJECT' | 'REQUEST_CHANGES' | null>(null);
  const [actionComments, setActionComments] = useState<string>('');
  const [actionBusy, setActionBusy] = useState<boolean>(false);
  const [actionSuccessNotice, setActionSuccessNotice] = useState<string | null>(null);

  // Quick comment form
  const [newComment, setNewComment] = useState<string>('');
  const [commentBusy, setCommentBusy] = useState<boolean>(false);

  // Map of brand kit ID -> kit name
  const kitMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const k of brandKits) {
      map.set(k.id, k.name);
    }
    return map;
  }, [brandKits]);

  const loadQueueData = useCallback(async () => {
    if (!activeOrganisationId) return;
    setLoading(true);
    setError(null);
    try {
      const [kitsList, subsList] = await Promise.all([
        fetchBrandKits(activeOrganisationId).catch(() => []),
        fetchContentSubmissions(activeOrganisationId, {
          status: activeTab === 'ALL' ? undefined : activeTab,
          limit: 200,
        }),
      ]);
      setBrandKits(kitsList);
      setSubmissions(subsList);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load approvals queue.');
    } finally {
      setLoading(false);
    }
  }, [activeOrganisationId, activeTab]);

  useEffect(() => {
    void loadQueueData();
  }, [loadQueueData]);

  // Load single submission detail when selected
  const openDetail = async (submissionId: string) => {
    if (!activeOrganisationId) return;
    setSelectedSubId(submissionId);
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    setActionSuccessNotice(null);
    try {
      const data = await fetchSubmissionDetail(activeOrganisationId, submissionId);
      setDetail(data);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Failed to fetch submission details.');
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setSelectedSubId(null);
    setDetail(null);
    setDetailError(null);
    setConfirmAction(null);
    setActionComments('');
    setActionSuccessNotice(null);
  };

  // Submit decision (Approve / Reject / Request Changes)
  const executeDecision = async () => {
    if (!activeOrganisationId || !selectedSubId || !confirmAction) return;
    setActionBusy(true);
    try {
      const updated = await submitApprovalDecision(activeOrganisationId, selectedSubId, {
        decision: confirmAction,
        comments: actionComments.trim() ? actionComments.trim() : null,
      });
      setDetail(updated);
      setActionSuccessNotice(`Submission successfully marked as ${confirmAction}.`);
      setConfirmAction(null);
      setActionComments('');
      // Refresh the queue in the background
      void loadQueueData();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Decision execution failed');
    } finally {
      setActionBusy(false);
    }
  };

  // Add Reviewer Comment
  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrganisationId || !selectedSubId || !newComment.trim()) return;
    setCommentBusy(true);
    try {
      const updated = await addReviewComment(activeOrganisationId, selectedSubId, newComment.trim());
      setDetail(updated);
      setNewComment('');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to add comment');
    } finally {
      setCommentBusy(false);
    }
  };

  // Client-side search filtering by title, submitter, reviewer, brand kit (SEC-09)
  const filteredSubmissions = useMemo(() => {
    let list = submissions;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter((s) => {
        const titleMatch = s.title.toLowerCase().includes(q);
        const submitterMatch = (s.submitted_by_name || '').toLowerCase().includes(q);
        const reviewerMatch = (s.assigned_reviewer_name || s.reviewed_by_name || '').toLowerCase().includes(q);
        const kitName = (kitMap.get(s.brand_kit_id) || '').toLowerCase();
        return titleMatch || submitterMatch || reviewerMatch || kitName.includes(q);
      });
    }
    return list;
  }, [submissions, searchQuery, kitMap]);

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300 mb-2">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>Human Review & Approval Inbox</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Approvals Queue</h1>
          <p className="text-sm text-slate-400 mt-1">
            Review submitted marketing copy, inspect compliance findings with cited evidence, and grant cryptographic approvals.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void loadQueueData()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-800 transition disabled:opacity-50"
            title="Reload approvals queue"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh Queue</span>
          </button>
        </div>
      </div>

      {/* Filter Tabs & Search Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2 p-1 rounded-xl bg-slate-900/80 border border-slate-800">
          {(
            [
              { key: 'ALL', label: 'All Submissions' },
              { key: 'PENDING_REVIEW', label: 'Pending Review' },
              { key: 'UNDER_REVIEW', label: 'Under Review' },
              { key: 'APPROVED', label: 'Approved' },
              { key: 'CHANGES_REQUESTED', label: 'Changes Requested' },
              { key: 'REJECTED', label: 'Rejected' },
            ] as const
          ).map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                activeTab === tab.key
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative min-w-[260px]">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by title, brand, or reviewer..."
            className="w-full rounded-xl bg-slate-900 border border-slate-800 pl-10 pr-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => void loadQueueData()}
            className="underline hover:text-rose-100"
          >
            Retry
          </button>
        </div>
      )}

      {/* Queue Table */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden shadow-sm">
        {loading ? (
          <div className="p-8 space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-12 w-full animate-pulse rounded-lg bg-slate-800/50" />
            ))}
          </div>
        ) : filteredSubmissions.length === 0 ? (
          <div className="py-16 px-6 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-800 text-slate-400 mb-3">
              <FileCheck2 className="h-6 w-6" />
            </div>
            <h3 className="text-base font-semibold text-white">No submissions found</h3>
            <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
              {searchQuery
                ? 'No items match your active search query.'
                : activeTab === 'ALL'
                ? 'No content submissions have been created in this organisation yet.'
                : `No submissions currently in status ${activeTab.replace('_', ' ')}.`}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="border-b border-slate-800 bg-slate-950/60 uppercase tracking-wider text-[11px] text-slate-400">
                <tr>
                  <th className="py-3.5 px-4 font-semibold">Title & Revision</th>
                  <th className="py-3.5 px-4 font-semibold">Brand Kit</th>
                  <th className="py-3.5 px-4 font-semibold">Submitter</th>
                  <th className="py-3.5 px-4 font-semibold">Compliance Score</th>
                  <th className="py-3.5 px-4 font-semibold">Status</th>
                  <th className="py-3.5 px-4 font-semibold">Reviewer</th>
                  <th className="py-3.5 px-4 font-semibold">Submitted</th>
                  <th className="py-3.5 px-4 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredSubmissions.map((sub) => {
                  const statusInfo = STATUS_BADGE[sub.status] || {
                    label: sub.status,
                    badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
                  };
                  const kitName = kitMap.get(sub.brand_kit_id) || 'Primary Brand Kit';
                  const isPass = sub.result === 'PASS';

                  return (
                    <tr
                      key={sub.id}
                      className="hover:bg-slate-800/30 transition cursor-pointer"
                      onClick={() => void openDetail(sub.id)}
                    >
                      <td className="py-3.5 px-4">
                        <div className="font-medium text-white">{sub.title}</div>
                        <div className="text-[11px] text-slate-500">Rev #{sub.revision_number}</div>
                      </td>
                      <td className="py-3.5 px-4 text-slate-300">{kitName}</td>
                      <td className="py-3.5 px-4 text-slate-300">
                        <span className="font-medium text-slate-200">
                          {sub.submitted_by_name || '—'}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        {sub.score !== null ? (
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`font-semibold ${
                                isPass ? 'text-emerald-400' : 'text-rose-400'
                              }`}
                            >
                              {sub.score}/100
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.2 text-[10px] font-medium border ${
                                isPass
                                  ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                                  : 'bg-rose-500/10 text-rose-300 border-rose-500/30'
                              }`}
                            >
                              {sub.result}
                            </span>
                          </div>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${statusInfo.badge}`}
                        >
                          {statusInfo.label}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-slate-400">
                        {sub.assigned_reviewer_name ? (
                          <div className="flex items-center gap-1">
                            <UserCheck className="h-3.5 w-3.5 text-indigo-400" />
                            <span>{sub.assigned_reviewer_name}</span>
                          </div>
                        ) : sub.reviewed_by_name ? (
                          <span>{sub.reviewed_by_name}</span>
                        ) : (
                          <span className="text-slate-500 text-[11px]">Unassigned</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-slate-400 text-[11px]">
                        {new Date(sub.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void openDetail(sub.id);
                          }}
                          className="inline-flex items-center gap-1 rounded-lg bg-indigo-600/10 border border-indigo-500/30 px-3 py-1 text-xs font-medium text-indigo-300 hover:bg-indigo-600/20 transition"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          <span>Inspect</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Review Modal / Drawer */}
      {selectedSubId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="relative w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl my-8 overflow-hidden flex flex-col max-h-[90vh]">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4 bg-slate-950/70">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-400">
                  <FileText className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">
                    {detail?.title || 'Loading submission...'}
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span>Revision #{detail?.revision_number ?? 1}</span>
                    <span>•</span>
                    <span>{detail ? kitMap.get(detail.brand_kit_id) || 'Brand Kit' : ''}</span>
                    <span>•</span>
                    <span>Status: {detail?.status}</span>
                    {detail?.submitted_by_name && (
                      <>
                        <span>•</span>
                        <span>Submitter: {detail.submitted_by_name}</span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              <button
                type="button"
                onClick={closeDetail}
                className="rounded-lg p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {actionSuccessNotice && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-300 flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>{actionSuccessNotice}</span>
                </div>
              )}

              {detailLoading ? (
                <div className="py-12 space-y-4">
                  <div className="h-8 w-1/3 animate-pulse rounded bg-slate-800" />
                  <div className="h-24 w-full animate-pulse rounded bg-slate-800" />
                </div>
              ) : detailError ? (
                <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-xs text-rose-300">
                  {detailError}
                </div>
              ) : detail ? (
                <>
                  {/* Score & Telemetry Banner */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                      <div className="text-xs text-slate-400">Deterministic Score</div>
                      <div className="mt-1 text-2xl font-bold text-white flex items-center gap-2">
                        <span>{detail.analysis?.score ?? '—'}/100</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
                            detail.analysis?.result === 'PASS'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : 'bg-rose-500/20 text-rose-300'
                          }`}
                        >
                          {detail.analysis?.result}
                        </span>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                      <div className="text-xs text-slate-400">Rules Evaluated</div>
                      <div className="mt-1 text-2xl font-bold text-white">
                        {detail.analysis?.rules_evaluated ?? 0}
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                      <div className="text-xs text-slate-400">Findings & Violations</div>
                      <div className="mt-1 text-2xl font-bold text-white">
                        {detail.analysis?.findings.length ?? 0}
                      </div>
                    </div>
                  </div>

                  {/* Execution Mode & Fallback Notice */}
                  {detail.analysis?.scoring?.engine_mode === 'DETERMINISTIC_FALLBACK' && (
                    <div className="rounded-xl border border-amber-500/40 bg-amber-950/20 p-3 text-xs text-amber-200 flex items-start gap-2.5">
                      <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-bold">Deterministic Fallback: </span>
                        <span>
                          {detail.analysis.scoring.ai_status_message ||
                            'AI provider unconfigured. Evaluated using authoritative deterministic rules only.'}
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Semantic Assessment Telemetry Pill */}
                  {detail.analysis?.scoring?.semantic_assessment && (
                    <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-3 text-xs flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 text-indigo-300 font-semibold">
                        <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
                        <span>AI Grounding Telemetry</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-slate-300 text-[11px] font-mono">
                        <span>{detail.analysis.scoring.semantic_assessment.claims_extracted} Claims</span>
                        <span className="text-emerald-400">
                          {detail.analysis.scoring.semantic_assessment.claims_verified} Verified
                        </span>
                        <span className="text-rose-400">
                          {detail.analysis.scoring.semantic_assessment.claims_contradicted} Contradicted
                        </span>
                        <span className="text-amber-400">
                          {detail.analysis.scoring.semantic_assessment.claims_unverified} Unverified
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Submitted Content Display */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                      Submitted Copy
                    </h4>
                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-xs font-mono text-slate-200 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                      {detail.content_text}
                    </div>
                  </div>

                  {/* Compliance Findings & Evidence */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
                      <ShieldAlert className="h-4 w-4 text-amber-400" />
                      <span>Violations & Evidence Citations ({detail.analysis?.findings.length ?? 0})</span>
                    </h4>

                    {(!detail.analysis?.findings || detail.analysis.findings.length === 0) ? (
                      <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 text-xs text-emerald-300 flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4" />
                        <span>Zero rule violations detected. All brand rules passed.</span>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {detail.analysis.findings.map((finding) => (
                          <div
                            key={finding.finding_id}
                            className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2.5"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-slate-100 text-xs">
                                {finding.rule_title || finding.title || 'Rule Violation'} ({finding.rule_code})
                              </span>
                              <span
                                className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase ${
                                  SEV_BADGE[finding.severity] || SEV_BADGE.MEDIUM
                                }`}
                              >
                                {finding.severity}
                              </span>
                            </div>

                            <p className="text-xs text-slate-300">{finding.explanation}</p>

                            {/* Unverified Guard Explicit Callout */}
                            {(finding.kind === 'UNVERIFIED_CLAIM' || finding.status === 'UNVERIFIED') && (
                              <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-2 text-[11px] text-amber-300 flex items-start gap-2">
                                <ShieldAlert className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                                <span>
                                  <strong>Unverified Guard:</strong> Claim could not be verified against approved guideline documents.
                                </span>
                              </div>
                            )}

                            {/* Guideline Chunk Evidence Citation */}
                            {finding.citation && (
                              <div className="rounded-lg border border-indigo-500/30 bg-indigo-950/30 p-2.5 text-[11px] text-slate-300 space-y-1">
                                <div className="flex items-center justify-between font-semibold text-indigo-300">
                                  <span className="flex items-center gap-1.5">
                                    <BookOpen className="h-3.5 w-3.5 text-indigo-400" />
                                    <span>{finding.citation.document_title}</span>
                                  </span>
                                  <span className="font-mono text-[10px] text-slate-400">
                                    Chunk: {finding.citation.chunk_id.slice(0, 8)}...
                                    {finding.citation.page_number ? ` · p.${finding.citation.page_number}` : ''}
                                  </span>
                                </div>
                                <blockquote className="italic text-slate-400 font-mono text-[10px] bg-slate-950/50 p-2 rounded border border-indigo-500/10">
                                  "{finding.citation.content || finding.evidence_excerpt}"
                                </blockquote>
                              </div>
                            )}

                            {!finding.citation && finding.evidence_excerpt && (
                              <div className="rounded-lg border border-slate-800/80 bg-slate-900/60 p-2.5 text-[11px] text-slate-400">
                                <span className="text-indigo-400 font-semibold">Evidence: </span>
                                <span className="font-mono">"{finding.evidence_excerpt}"</span>
                              </div>
                            )}

                            {finding.recommended_correction && (
                              <div className="text-[11px] text-emerald-400">
                                <span className="font-semibold">Recommended Correction: </span>
                                <span>{finding.recommended_correction}</span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Review Audit History */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
                      <Clock4 className="h-4 w-4 text-indigo-400" />
                      <span>Review Action Log</span>
                    </h4>
                    {detail.review_history.length === 0 ? (
                      <p className="text-xs text-slate-500">No review actions recorded yet.</p>
                    ) : (
                      <div className="space-y-2">
                        {detail.review_history.map((action) => (
                          <div
                            key={action.id}
                            className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-xs flex items-start justify-between gap-4"
                          >
                            <div>
                              <div className="font-semibold text-white">
                                {action.action.replace(/_/g, ' ')}
                                <span className="text-slate-400 font-normal ml-2">
                                  by {action.actor_name || 'System / Reviewer'}
                                </span>
                              </div>
                              {action.comments && (
                                <p className="mt-1 text-slate-300">{action.comments}</p>
                              )}
                            </div>
                            <span className="text-[10px] text-slate-500 shrink-0">
                              {new Date(action.created_at).toLocaleString()}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Add Reviewer Comment Form */}
                  <form onSubmit={handleAddComment} className="pt-2">
                    <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                      Add Reviewer Note / Comment
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={newComment}
                        onChange={(e) => setNewComment(e.target.value)}
                        placeholder="Leave feedback or guidance for the content creator..."
                        className="flex-1 rounded-xl bg-slate-950 border border-slate-800 px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                      />
                      <button
                        type="submit"
                        disabled={commentBusy || !newComment.trim()}
                        className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 transition"
                      >
                        {commentBusy ? 'Posting...' : 'Post Note'}
                      </button>
                    </div>
                  </form>
                </>
              ) : null}
            </div>

            {/* Modal Footer / Review Actions */}
            <div className="border-t border-slate-800 bg-slate-950/80 px-6 py-4 flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs text-slate-400">
                {detail?.submitted_by_user_id === user?.id ? (
                  <span className="text-amber-400 font-medium flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    Independent review required: You submitted this copy.
                  </span>
                ) : canDecide ? (
                  <span className="text-emerald-400 font-medium">
                    ✓ Authorised to approve or reject
                  </span>
                ) : (
                  <span className="text-slate-500">
                    Read-only reviewer mode (requires approval:decide for final action)
                  </span>
                )}
              </div>

              {canDecide && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmAction('REQUEST_CHANGES')}
                    disabled={actionBusy || detail?.submitted_by_user_id === user?.id}
                    className="rounded-xl border border-orange-500/30 bg-orange-500/10 px-4 py-2 text-xs font-semibold text-orange-300 hover:bg-orange-500/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Request Changes
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmAction('REJECT')}
                    disabled={actionBusy || detail?.submitted_by_user_id === user?.id}
                    className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmAction('APPROVE')}
                    disabled={actionBusy || detail?.submitted_by_user_id === user?.id}
                    className="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-500 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Approve Copy
                  </button>
                </div>
              )}
            </div>

            {/* Confirmation Sub-Modal */}
            {confirmAction && (
              <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
                <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 space-y-4">
                  <h4 className="text-base font-bold text-white">
                    Confirm Decision: {confirmAction.replace('_', ' ')}
                  </h4>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {confirmAction === 'APPROVE'
                      ? 'Are you sure you want to approve this marketing submission? This decision is immutable and recorded in the audit log.'
                      : confirmAction === 'REJECT'
                      ? 'Are you sure you want to reject this submission? Please provide feedback for the author.'
                      : 'Request revisions from the author. The submission status will change to CHANGES_REQUESTED.'}
                  </p>

                  <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1">
                      Reason / Review Comments (Optional)
                    </label>
                    <textarea
                      value={actionComments}
                      onChange={(e) => setActionComments(e.target.value)}
                      rows={3}
                      placeholder="Add guidance or notes for this decision..."
                      className="w-full rounded-xl bg-slate-950 border border-slate-800 p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => setConfirmAction(null)}
                      disabled={actionBusy}
                      className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700 transition"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => void executeDecision()}
                      disabled={actionBusy}
                      className={`rounded-xl px-4 py-2 text-xs font-semibold text-white transition ${
                        confirmAction === 'APPROVE'
                          ? 'bg-emerald-600 hover:bg-emerald-500'
                          : confirmAction === 'REJECT'
                          ? 'bg-rose-600 hover:bg-rose-500'
                          : 'bg-orange-600 hover:bg-orange-500'
                      }`}
                    >
                      {actionBusy ? 'Processing...' : `Confirm ${confirmAction.replace('_', ' ')}`}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
export default ApprovalsPage;
