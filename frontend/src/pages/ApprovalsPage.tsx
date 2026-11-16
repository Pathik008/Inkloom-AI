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
  CRITICAL: 'bg-[#EF4444]/15 text-[#EF4444] border border-[#EF4444]/40',
  HIGH: 'bg-[#F97316]/15 text-[#F97316] border border-[#F97316]/40',
  MEDIUM: 'bg-[#F59E0B]/15 text-[#F59E0B] border border-[#F59E0B]/40',
  LOW: 'bg-[#38BDF8]/15 text-[#38BDF8] border border-[#38BDF8]/40',
  INFO: 'bg-[#71717A]/20 text-[#A1A1AA] border border-[#424242]',
};

const STATUS_BADGE: Record<string, { label: string; badge: string }> = {
  PENDING_REVIEW: { label: 'Pending Review', badge: 'bg-[#F59E0B]/15 text-[#F59E0B] border border-[#F59E0B]/30' },
  UNDER_REVIEW: { label: 'Under Review', badge: 'bg-[#38BDF8]/15 text-[#38BDF8] border border-[#38BDF8]/30' },
  APPROVED: { label: 'Approved', badge: 'bg-[#10A37F]/15 text-[#10A37F] border border-[#10A37F]/30' },
  REJECTED: { label: 'Rejected', badge: 'bg-[#EF4444]/15 text-[#EF4444] border border-[#EF4444]/30' },
  CHANGES_REQUESTED: { label: 'Changes Requested', badge: 'bg-[#F97316]/15 text-[#F97316] border border-[#F97316]/30' },
  DRAFT: { label: 'Draft', badge: 'bg-[#212121] text-[#A1A1AA] border border-[#424242]' },
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
    setDetailError(null);
    try {
      const updated = await submitApprovalDecision(
        activeOrganisationId,
        selectedSubId,
        {
          decision: confirmAction,
          comments: actionComments.trim() || undefined,
        },
      );

      setActionSuccessNotice(
        confirmAction === 'APPROVE'
          ? 'Content submission successfully approved.'
          : confirmAction === 'REJECT'
          ? 'Content submission rejected.'
          : 'Changes requested from author.',
      );

      setConfirmAction(null);
      setActionComments('');
      setDetail(updated as unknown as SubmissionDetail);
      await loadQueueData();
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Failed to record approval decision.');
    } finally {
      setActionBusy(false);
    }
  };

  // Post reviewer note
  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrganisationId || !selectedSubId || !newComment.trim()) return;

    setCommentBusy(true);
    try {
      await addReviewComment(activeOrganisationId, selectedSubId, newComment.trim());
      setNewComment('');
      const updated = await fetchSubmissionDetail(activeOrganisationId, selectedSubId);
      setDetail(updated);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Failed to post review comment.');
    } finally {
      setCommentBusy(false);
    }
  };

  // Filter submissions by search query
  const filteredSubmissions = useMemo(() => {
    if (!searchQuery.trim()) return submissions;
    const q = searchQuery.toLowerCase();
    return submissions.filter((s) => {
      const titleMatch = s.title.toLowerCase().includes(q);
      const kitName = (kitMap.get(s.brand_kit_id) || '').toLowerCase();
      const reviewer = (s.assigned_reviewer_name || s.reviewed_by_name || '').toLowerCase();
      return titleMatch || kitName.includes(q) || reviewer.includes(q);
    });
  }, [submissions, searchQuery, kitMap]);

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">
      {/* Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[#10A37F]/30 bg-[#10A37F]/10 px-3 py-0.5 text-xs font-semibold text-[#10A37F] mb-2">
            <UserCheck className="h-3.5 w-3.5" />
            <span>Maker-Checker Governance Pipeline</span>
          </div>
          <h1 className="text-xl font-semibold text-[#ECECEC] tracking-tight flex items-center gap-2.5">
            <FileCheck2 className="h-6 w-6 text-[#10A37F]" />
            <span>Independent Reviewer Approval Inbox</span>
          </h1>
          <p className="text-xs text-[#A1A1AA] mt-1">
            Review submitted marketing collateral, inspect evidence citations, and record immutable approval or rejection decisions.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void loadQueueData()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-[#424242] bg-[#2F2F2F] hover:bg-[#424242] px-3.5 py-2 text-xs font-medium text-[#ECECEC] transition disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Queue</span>
        </button>
      </div>

      {/* Filter Tabs & Search Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-lg bg-[#212121] border border-[#424242]">
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
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === tab.key
                  ? 'bg-[#424242] text-[#ECECEC]'
                  : 'text-[#A1A1AA] hover:text-[#ECECEC] hover:bg-[#2F2F2F]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative min-w-[260px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#71717A]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by title, brand, or reviewer..."
            className="w-full rounded-lg bg-[#212121] border border-[#424242] pl-9 pr-3.5 py-1.5 text-xs text-[#ECECEC] placeholder-[#71717A] focus:outline-none focus:border-[#10A37F]"
          />
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-3.5 text-xs text-[#EF4444] flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => void loadQueueData()}
            className="underline hover:text-[#ECECEC]"
          >
            Retry
          </button>
        </div>
      )}

      {/* Queue Table */}
      <div className="rounded-xl border border-[#424242] bg-[#2F2F2F] overflow-hidden shadow-sm">
        {loading ? (
          <div className="p-8 space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-10 w-full animate-pulse rounded bg-[#212121]" />
            ))}
          </div>
        ) : filteredSubmissions.length === 0 ? (
          <div className="py-14 px-6 text-center">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg bg-[#212121] text-[#71717A] mb-2.5">
              <FileCheck2 className="h-5 w-5" />
            </div>
            <h3 className="text-sm font-semibold text-[#ECECEC]">No submissions found</h3>
            <p className="text-xs text-[#71717A] mt-0.5 max-w-sm mx-auto">
              {searchQuery
                ? 'No items match your active search query.'
                : activeTab === 'ALL'
                ? 'No content submissions have been created in this organisation yet.'
                : `No submissions currently in status ${activeTab.replace('_', ' ')}.`}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-[#ECECEC]">
              <thead className="border-b border-[#424242] bg-[#212121] uppercase tracking-wider text-[10px] text-[#A1A1AA]">
                <tr>
                  <th className="py-3 px-4 font-semibold">Title & Revision</th>
                  <th className="py-3 px-4 font-semibold">Brand Kit</th>
                  <th className="py-3 px-4 font-semibold">Submitter</th>
                  <th className="py-3 px-4 font-semibold">Compliance Score</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                  <th className="py-3 px-4 font-semibold">Reviewer</th>
                  <th className="py-3 px-4 font-semibold">Submitted</th>
                  <th className="py-3 px-4 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#424242]/50">
                {filteredSubmissions.map((sub) => {
                  const statusInfo = STATUS_BADGE[sub.status] || {
                    label: sub.status,
                    badge: 'bg-[#212121] text-[#A1A1AA] border border-[#424242]',
                  };
                  const kitName = kitMap.get(sub.brand_kit_id) || 'Primary Brand Kit';
                  const isPass = sub.result === 'PASS';

                  return (
                    <tr
                      key={sub.id}
                      className="hover:bg-[#424242]/20 transition-colors cursor-pointer"
                      onClick={() => void openDetail(sub.id)}
                    >
                      <td className="py-3 px-4">
                        <div className="font-medium text-[#ECECEC]">{sub.title}</div>
                        <div className="text-[10px] text-[#71717A] font-mono">Rev #{sub.revision_number}</div>
                      </td>
                      <td className="py-3 px-4 text-[#A1A1AA]">{kitName}</td>
                      <td className="py-3 px-4 text-[#A1A1AA]">
                        <span className="font-medium text-[#ECECEC]">
                          {sub.submitted_by_name || '—'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {sub.score !== null ? (
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`font-semibold ${
                                isPass ? 'text-[#10A37F]' : 'text-[#EF4444]'
                              }`}
                            >
                              {sub.score}/100
                            </span>
                            <span
                              className={`rounded px-1.5 py-0.2 text-[10px] font-medium border ${
                                isPass
                                  ? 'bg-[#10A37F]/15 text-[#10A37F] border-[#10A37F]/30'
                                  : 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30'
                              }`}
                            >
                              {sub.result}
                            </span>
                          </div>
                        ) : (
                          <span className="text-[#71717A]">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${statusInfo.badge}`}
                        >
                          {statusInfo.label}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-[#A1A1AA]">
                        {sub.assigned_reviewer_name ? (
                          <div className="flex items-center gap-1">
                            <UserCheck className="h-3.5 w-3.5 text-[#10A37F]" />
                            <span>{sub.assigned_reviewer_name}</span>
                          </div>
                        ) : sub.reviewed_by_name ? (
                          <span>{sub.reviewed_by_name}</span>
                        ) : (
                          <span className="text-[#71717A] text-[10px]">Unassigned</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-[#71717A] text-[11px]">
                        {new Date(sub.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void openDetail(sub.id);
                          }}
                          className="inline-flex items-center gap-1 rounded-md bg-[#212121] border border-[#424242] px-2.5 py-1 text-xs font-medium text-[#ECECEC] hover:bg-[#424242] transition"
                        >
                          <Eye className="h-3.5 w-3.5 text-[#10A37F]" />
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 overflow-y-auto">
          <div className="relative w-full max-w-4xl rounded-xl border border-[#424242] bg-[#2F2F2F] shadow-xl my-8 overflow-hidden flex flex-col max-h-[90vh]">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-[#424242] px-6 py-4 bg-[#212121]">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#2F2F2F] border border-[#424242] text-[#10A37F]">
                  <FileText className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-[#ECECEC]">
                    {detail?.title || 'Loading submission...'}
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-[#A1A1AA]">
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
                className="rounded-lg p-1 text-[#A1A1AA] hover:text-[#ECECEC] hover:bg-[#424242] transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-5 bg-[#2F2F2F]">
              {actionSuccessNotice && (
                <div className="rounded-lg border border-[#10A37F]/30 bg-[#10A37F]/10 p-3 text-xs text-[#10A37F] flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>{actionSuccessNotice}</span>
                </div>
              )}

              {detailLoading ? (
                <div className="py-12 space-y-4">
                  <div className="h-8 w-1/3 animate-pulse rounded bg-[#212121]" />
                  <div className="h-24 w-full animate-pulse rounded bg-[#212121]" />
                </div>
              ) : detailError ? (
                <div className="p-4 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 text-xs text-[#EF4444]">
                  {detailError}
                </div>
              ) : detail ? (
                <>
                  {/* Score & Telemetry Banner */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5">
                      <div className="text-xs text-[#A1A1AA]">Deterministic Score</div>
                      <div className="mt-1 text-2xl font-bold text-[#ECECEC] flex items-center gap-2">
                        <span>{detail.analysis?.score ?? '—'}/100</span>
                        <span
                          className={`rounded px-1.5 py-0.2 text-xs font-semibold ${
                            detail.analysis?.result === 'PASS'
                              ? 'bg-[#10A37F]/15 text-[#10A37F]'
                              : 'bg-[#EF4444]/15 text-[#EF4444]'
                          }`}
                        >
                          {detail.analysis?.result}
                        </span>
                      </div>
                    </div>

                    <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5">
                      <div className="text-xs text-[#A1A1AA]">Rules Evaluated</div>
                      <div className="mt-1 text-2xl font-bold text-[#ECECEC]">
                        {detail.analysis?.rules_evaluated ?? 0}
                      </div>
                    </div>

                    <div className="rounded-lg border border-[#424242] bg-[#212121] p-3.5">
                      <div className="text-xs text-[#A1A1AA]">Findings & Violations</div>
                      <div className="mt-1 text-2xl font-bold text-[#ECECEC]">
                        {detail.analysis?.findings.length ?? 0}
                      </div>
                    </div>
                  </div>

                  {/* Execution Mode & Fallback Notice */}
                  {detail.analysis?.scoring?.engine_mode === 'DETERMINISTIC_FALLBACK' && (
                    <div className="rounded-lg border border-[#F59E0B]/30 bg-[#212121] p-3 text-xs text-[#F59E0B] flex items-start gap-2.5">
                      <ShieldAlert className="h-4 w-4 text-[#F59E0B] shrink-0 mt-0.5" />
                      <div>
                        <span className="font-semibold">Deterministic Fallback: </span>
                        <span className="text-[#ECECEC]">
                          {detail.analysis.scoring.ai_status_message ||
                            'AI provider unconfigured. Evaluated using authoritative deterministic rules only.'}
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Semantic Assessment Telemetry Pill */}
                  {detail.analysis?.scoring?.semantic_assessment && (
                    <div className="rounded-lg border border-[#424242] bg-[#212121] p-3 text-xs flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 text-[#10A37F] font-semibold">
                        <Sparkles className="h-3.5 w-3.5 text-[#10A37F]" />
                        <span>AI Grounding Telemetry</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-[#ECECEC] text-[11px] font-mono">
                        <span>{detail.analysis.scoring.semantic_assessment.claims_extracted} Claims</span>
                        <span className="text-[#10A37F]">
                          {detail.analysis.scoring.semantic_assessment.claims_verified} Verified
                        </span>
                        <span className="text-[#EF4444]">
                          {detail.analysis.scoring.semantic_assessment.claims_contradicted} Contradicted
                        </span>
                        <span className="text-[#F59E0B]">
                          {detail.analysis.scoring.semantic_assessment.claims_unverified} Unverified
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Submitted Content Display */}
                  <div className="space-y-1.5">
                    <h4 className="text-xs font-semibold text-[#A1A1AA] uppercase tracking-wider">
                      Submitted Copy
                    </h4>
                    <div className="rounded-lg border border-[#424242] bg-[#212121] p-4 text-xs font-mono text-[#ECECEC] whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                      {detail.content_text}
                    </div>
                  </div>

                  {/* Compliance Findings & Evidence */}
                  <div className="space-y-2.5">
                    <h4 className="text-xs font-semibold text-[#A1A1AA] uppercase tracking-wider flex items-center gap-2">
                      <ShieldAlert className="h-4 w-4 text-[#F59E0B]" />
                      <span>Violations & Evidence Citations ({detail.analysis?.findings.length ?? 0})</span>
                    </h4>

                    {(!detail.analysis?.findings || detail.analysis.findings.length === 0) ? (
                      <div className="rounded-lg border border-[#10A37F]/30 bg-[#10A37F]/10 p-3.5 text-xs text-[#10A37F] flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4" />
                        <span>Zero rule violations detected. All brand rules passed.</span>
                      </div>
                    ) : (
                      <div className="space-y-2.5">
                        {detail.analysis.findings.map((finding) => (
                          <div
                            key={finding.finding_id}
                            className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 space-y-2"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-[#ECECEC] text-xs">
                                {finding.rule_title || finding.title || 'Rule Violation'} ({finding.rule_code})
                              </span>
                              <span
                                className={`rounded px-1.5 py-0.2 text-[10px] font-semibold uppercase ${
                                  SEV_BADGE[finding.severity] || SEV_BADGE.MEDIUM
                                }`}
                              >
                                {finding.severity}
                              </span>
                            </div>

                            <p className="text-xs text-[#A1A1AA]">{finding.explanation}</p>

                            {/* Unverified Guard Explicit Callout */}
                            {(finding.kind === 'UNVERIFIED_CLAIM' || finding.status === 'UNVERIFIED') && (
                              <div className="rounded border border-[#F59E0B]/30 bg-[#F59E0B]/10 p-2 text-[11px] text-[#F59E0B] flex items-start gap-2">
                                <ShieldAlert className="h-3.5 w-3.5 text-[#F59E0B] shrink-0 mt-0.5" />
                                <span>
                                  <strong>Unverified Guard:</strong> Claim could not be verified against approved guideline documents.
                                </span>
                              </div>
                            )}

                            {/* Guideline Chunk Evidence Citation */}
                            {finding.citation && (
                              <div className="rounded border border-[#424242] bg-[#2F2F2F] p-2.5 text-[11px] text-[#ECECEC] space-y-1">
                                <div className="flex items-center justify-between font-semibold text-[#10A37F]">
                                  <span className="flex items-center gap-1.5">
                                    <BookOpen className="h-3.5 w-3.5 text-[#10A37F]" />
                                    <span>{finding.citation.document_title}</span>
                                  </span>
                                  <span className="font-mono text-[10px] text-[#71717A]">
                                    Chunk: {finding.citation.chunk_id.slice(0, 8)}...
                                    {finding.citation.page_number ? ` · p.${finding.citation.page_number}` : ''}
                                  </span>
                                </div>
                                <blockquote className="italic text-[#A1A1AA] font-mono text-[10px] bg-[#212121] p-2 rounded border border-[#424242]">
                                  "{finding.citation.content || finding.evidence_excerpt}"
                                </blockquote>
                              </div>
                            )}

                            {!finding.citation && finding.evidence_excerpt && (
                              <div className="rounded border border-[#424242] bg-[#2F2F2F] p-2 text-[11px] text-[#A1A1AA]">
                                <span className="text-[#10A37F] font-semibold">Evidence: </span>
                                <span className="font-mono">"{finding.evidence_excerpt}"</span>
                              </div>
                            )}

                            {finding.recommended_correction && (
                              <div className="text-[11px] text-[#10A37F]">
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
                  <div className="space-y-2.5">
                    <h4 className="text-xs font-semibold text-[#A1A1AA] uppercase tracking-wider flex items-center gap-2">
                      <Clock4 className="h-4 w-4 text-[#10A37F]" />
                      <span>Review Action Log</span>
                    </h4>
                    {detail.review_history.length === 0 ? (
                      <p className="text-xs text-[#71717A]">No review actions recorded yet.</p>
                    ) : (
                      <div className="space-y-2">
                        {detail.review_history.map((action) => (
                          <div
                            key={action.id}
                            className="rounded-lg border border-[#424242] bg-[#212121] p-3 text-xs flex items-start justify-between gap-4"
                          >
                            <div>
                              <div className="font-semibold text-[#ECECEC]">
                                {action.action.replace(/_/g, ' ')}
                                <span className="text-[#A1A1AA] font-normal ml-2">
                                  by {action.actor_name || 'System / Reviewer'}
                                </span>
                              </div>
                              {action.comments && (
                                <p className="mt-1 text-[#A1A1AA]">{action.comments}</p>
                              )}
                            </div>
                            <span className="text-[10px] text-[#71717A] shrink-0 font-mono">
                              {new Date(action.created_at).toLocaleString()}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Add Reviewer Comment Form */}
                  <form onSubmit={handleAddComment} className="pt-2">
                    <label className="block text-xs font-medium text-[#A1A1AA] mb-1.5">
                      Add Reviewer Note / Comment
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={newComment}
                        onChange={(e) => setNewComment(e.target.value)}
                        placeholder="Leave feedback or guidance for the content creator..."
                        className="flex-1 rounded-lg bg-[#212121] border border-[#424242] px-3 py-1.5 text-xs text-[#ECECEC] placeholder-[#71717A] focus:outline-none focus:border-[#10A37F]"
                      />
                      <button
                        type="submit"
                        disabled={commentBusy || !newComment.trim()}
                        className="rounded-lg bg-[#10A37F] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#0D8F70] disabled:opacity-50 transition-colors"
                      >
                        {commentBusy ? 'Posting...' : 'Post Note'}
                      </button>
                    </div>
                  </form>
                </>
              ) : null}
            </div>

            {/* Modal Footer / Review Actions */}
            <div className="border-t border-[#424242] bg-[#212121] px-6 py-3.5 flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs text-[#A1A1AA]">
                {detail?.submitted_by_user_id === user?.id ? (
                  <span className="text-[#F59E0B] font-medium flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    Independent review required: You submitted this copy.
                  </span>
                ) : canDecide ? (
                  <span className="text-[#10A37F] font-medium">
                    ✓ Authorised to approve or reject
                  </span>
                ) : (
                  <span className="text-[#71717A]">
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
                    className="rounded-lg border border-[#F59E0B]/40 bg-[#F59E0B]/10 px-3.5 py-1.5 text-xs font-semibold text-[#F59E0B] hover:bg-[#F59E0B]/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Request Changes
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmAction('REJECT')}
                    disabled={actionBusy || detail?.submitted_by_user_id === user?.id}
                    className="rounded-lg border border-[#EF4444]/40 bg-[#EF4444]/10 px-3.5 py-1.5 text-xs font-semibold text-[#EF4444] hover:bg-[#EF4444]/20 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmAction('APPROVE')}
                    disabled={actionBusy || detail?.submitted_by_user_id === user?.id}
                    className="rounded-lg bg-[#10A37F] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#0D8F70] transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Approve Copy
                  </button>
                </div>
              )}
            </div>

            {/* Confirmation Sub-Modal */}
            {confirmAction && (
              <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
                <div className="w-full max-w-md rounded-xl border border-[#424242] bg-[#2F2F2F] p-5 space-y-3.5 shadow-2xl">
                  <h4 className="text-sm font-semibold text-[#ECECEC]">
                    Confirm Decision: {confirmAction.replace('_', ' ')}
                  </h4>
                  <p className="text-xs text-[#A1A1AA] leading-relaxed">
                    {confirmAction === 'APPROVE'
                      ? 'Are you sure you want to approve this marketing submission? This decision is immutable and recorded in the audit log.'
                      : confirmAction === 'REJECT'
                      ? 'Are you sure you want to reject this submission? Please provide feedback for the author.'
                      : 'Request revisions from the author. The submission status will change to CHANGES_REQUESTED.'}
                  </p>

                  <div>
                    <label className="block text-xs font-medium text-[#A1A1AA] mb-1">
                      Reason / Review Comments (Optional)
                    </label>
                    <textarea
                      value={actionComments}
                      onChange={(e) => setActionComments(e.target.value)}
                      rows={3}
                      placeholder="Add guidance or notes for this decision..."
                      className="w-full rounded-lg bg-[#212121] border border-[#424242] p-2.5 text-xs text-[#ECECEC] placeholder-[#71717A] focus:outline-none focus:border-[#10A37F]"
                    />
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setConfirmAction(null)}
                      disabled={actionBusy}
                      className="rounded-lg border border-[#424242] bg-[#212121] px-3.5 py-1.5 text-xs font-medium text-[#A1A1AA] hover:bg-[#424242] hover:text-[#ECECEC] transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => void executeDecision()}
                      disabled={actionBusy}
                      className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold text-white transition-colors ${
                        confirmAction === 'APPROVE'
                          ? 'bg-[#10A37F] hover:bg-[#0D8F70]'
                          : confirmAction === 'REJECT'
                          ? 'bg-[#EF4444] hover:bg-[#DC2626]'
                          : 'bg-[#F59E0B] hover:bg-[#D97706]'
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
