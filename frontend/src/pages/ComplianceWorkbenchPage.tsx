import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Clock,
  FileCheck2,
  History,
  Loader2,
  MessageSquare,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Wand2,
  XCircle,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { apiRequest } from '../services/api';

interface Finding {
  finding_id: string;
  rule_code: string;
  rule_title: string;
  severity: string;
  kind: string;
  matched_text: string | null;
  start: number | null;
  end: number | null;
  evidence_excerpt: string | null;
  explanation: string;
  recommended_correction: string;
  correction: { replacement: string | null; append_text: string | null };
}

interface Analysis {
  score: number;
  result: 'PASS' | 'FAIL';
  rules_evaluated: number;
  findings: Finding[];
  scoring: {
    formula: string;
    pass_rule: string;
    total_penalty: number;
    breakdown: { severity: string; count: number; penalty_each: number; penalty_total: number }[];
  };
}

interface Comparison {
  score_before: number;
  score_after: number;
  score_delta: number;
  result_before: string;
  result_after: string;
  resolved_findings: Finding[];
  remaining_findings: Finding[];
  new_findings: Finding[];
  text_diff: string[];
}

interface ReviewAction {
  id: string;
  actor_user_id: string | null;
  actor_name: string | null;
  actor_email: string | null;
  action: string;
  comments: string | null;
  created_at: string;
}

interface LineageRevision {
  id: string;
  revision_number: number;
  title: string;
  status: string;
  score: number | null;
  result: string | null;
  created_at: string;
}

interface ReviewerUser {
  id: string;
  full_name: string;
  email: string;
  role: string;
}

interface Submission {
  id: string;
  brand_kit_id: string;
  brand_kit_version_id: string;
  parent_submission_id: string | null;
  revision_number: number;
  title: string;
  content_text: string;
  status: string;
  assigned_reviewer_id: string | null;
  assigned_reviewer_name: string | null;
  reviewed_by_user_id: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  reviewer_comments: string | null;
  created_at: string;
  analysis: Analysis | null;
  comparison: Comparison | null;
  review_history: ReviewAction[];
  all_revisions: LineageRevision[];
}

interface SubmissionSummary {
  id: string;
  brand_kit_id: string;
  title: string;
  score: number | null;
  result: string | null;
  status: string;
  assigned_reviewer_name?: string | null;
  reviewed_by_name?: string | null;
  revision_number: number;
  created_at: string;
}

interface Kit {
  id: string;
  name: string;
  active_version_id: string | null;
}

const SEV_COLOUR: Record<string, string> = {
  CRITICAL: 'bg-rose-500/20 text-rose-300 border border-rose-500/40',
  HIGH: 'bg-orange-500/20 text-orange-300 border border-orange-500/40',
  MEDIUM: 'bg-amber-500/20 text-amber-300 border border-amber-500/40',
  LOW: 'bg-sky-500/20 text-sky-300 border border-sky-500/40',
  INFO: 'bg-slate-500/20 text-slate-300 border border-slate-500/40',
};

const STATUS_COLOUR: Record<string, string> = {
  APPROVED: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40',
  PENDING_REVIEW: 'bg-amber-500/20 text-amber-300 border border-amber-500/40',
  CHANGES_REQUESTED: 'bg-orange-500/20 text-orange-300 border border-orange-500/40',
  REJECTED: 'bg-rose-500/20 text-rose-300 border border-rose-500/40',
  DRAFT: 'bg-slate-500/20 text-slate-300 border border-slate-500/40',
};

const MARK_COLOUR: Record<string, string> = {
  CRITICAL: 'bg-rose-500/40 text-white font-medium border-b-2 border-rose-400',
  HIGH: 'bg-orange-500/40 text-white font-medium border-b-2 border-orange-400',
  MEDIUM: 'bg-amber-500/40 text-white font-medium border-b-2 border-amber-400',
  LOW: 'bg-sky-500/40 text-white font-medium border-b-2 border-sky-400',
  INFO: 'bg-slate-500/40 text-white font-medium',
};

const input =
  'w-full rounded-xl bg-slate-950 border border-slate-700 px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none';

const DEMO_VIOLATION_SAMPLE =
  'Welcome to the new investment fund. We offer guaranteed returns and a 100% risk-free portfolio for all retail investors. Start investing today!';

const HighlightedText: React.FC<{ text: string; findings: Finding[] }> = ({ text, findings }) => {
  const spans = findings
    .filter((f) => f.start !== null && f.end !== null)
    .sort((a, b) => (a.start as number) - (b.start as number));

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach((f) => {
    const s = f.start as number;
    const e = f.end as number;
    if (s < cursor) return;
    parts.push(text.slice(cursor, s));
    parts.push(
      <mark
        key={f.finding_id}
        title={`${f.rule_code}: ${f.explanation}`}
        className={`rounded px-1.5 py-0.5 ${MARK_COLOUR[f.severity] ?? ''}`}
      >
        {text.slice(s, e)}
      </mark>,
    );
    cursor = e;
  });
  parts.push(text.slice(cursor));
  return (
    <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200 font-mono bg-slate-950/80 p-4 rounded-xl border border-slate-800">
      {parts}
    </div>
  );
};

export const ComplianceWorkbenchPage: React.FC = () => {
  const { activeOrganisationId: orgId, hasPermission } = useAuth();
  const canSubmit = hasPermission('content:create');
  const canDecide = hasPermission('approval:decide');
  const canReview = hasPermission('content:review');

  const [kits, setKits] = useState<Kit[]>([]);
  const [kitId, setKitId] = useState('');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [current, setCurrent] = useState<Submission | null>(null);
  const [history, setHistory] = useState<SubmissionSummary[]>([]);
  const [reviewers, setReviewers] = useState<ReviewerUser[]>([]);
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'PENDING_REVIEW' | 'APPROVED' | 'CHANGES_REQUESTED'>('ALL');

  // Human approval forms state
  const [selectedReviewerId, setSelectedReviewerId] = useState('');
  const [reviewerComment, setReviewerComment] = useState('');
  const [submitComment, setSubmitComment] = useState('');
  const [showSubmitModal, setShowSubmitModal] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const base = `/api/v1/organisations/${orgId}`;

  // 1. Fetch Kits, Reviewers and Submissions on mount or org switch
  const loadKitsAndSubmissions = useCallback(
    async (filterStatus?: string) => {
      if (!orgId) return;
      setError(null);
      try {
        const queryParams = filterStatus && filterStatus !== 'ALL' ? `?status=${filterStatus}` : '';
        const [kitsList, subsList, revsList] = await Promise.all([
          apiRequest<Kit[]>(`${base}/brand-kits`),
          apiRequest<SubmissionSummary[]>(`${base}/compliance/submissions${queryParams}`),
          canReview ? apiRequest<ReviewerUser[]>(`${base}/compliance/reviewers`).catch(() => []) : Promise.resolve([]),
        ]);
        setKits(kitsList);
        setHistory(subsList);
        setReviewers(revsList);

        const defaultKitId = kitsList[0]?.id || '';
        setKitId((cur) => cur || defaultKitId);

        // If user has previous submissions and none selected, load the latest one
        if (subsList.length > 0 && !current) {
          const latest = await apiRequest<Submission>(`${base}/compliance/submissions/${subsList[0].id}`);
          setCurrent(latest);
          setText(latest.content_text);
          setTitle(latest.title);
          setKitId(latest.brand_kit_id);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load brand kits or history.');
      }
    },
    [base, canReview, current, orgId],
  );

  useEffect(() => {
    void loadKitsAndSubmissions(statusFilter);
  }, [loadKitsAndSubmissions, statusFilter]);

  const call = useCallback(
    async (fn: () => Promise<Submission>, successMessage?: string) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        const s = await fn();
        setCurrent(s);
        setText(s.content_text);
        setTitle(s.title);
        setKitId(s.brand_kit_id);
        if (successMessage) {
          setNotice(successMessage);
        }
        // Refresh history
        void apiRequest<SubmissionSummary[]>(`${base}/compliance/submissions`).then(setHistory).catch(() => {});
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Operation failed');
      } finally {
        setBusy(false);
      }
    },
    [base],
  );

  const analysis = current?.analysis ?? null;
  const fixable = useMemo(
    () => analysis?.findings.some((f) => f.correction.replacement !== null || f.correction.append_text) ?? false,
    [analysis],
  );

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2.5">
            <FileCheck2 className="h-7 w-7 text-indigo-400" />
            <span>Compliance Review & Content Approval</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Automated deterministic evaluation combined with human reviewer approvals, revision lineages, and permanent audit trails.
          </p>
        </div>

        {/* Load Sample Button for Judges */}
        <button
          onClick={() => {
            setText(DEMO_VIOLATION_SAMPLE);
            setTitle('Acme Wealth Promotion (Deliberate Violations Demo)');
          }}
          className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-500/40 bg-indigo-500/10 px-3.5 py-2 text-xs font-semibold text-indigo-300 hover:bg-indigo-500/20 transition-colors"
        >
          <Sparkles className="h-3.5 w-3.5" />
          <span>Load Judge Demo Sample</span>
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200 flex items-start gap-3">
          <XCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {notice && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200 flex items-start gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
          <span>{notice}</span>
        </div>
      )}

      {/* Review Queue & History Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Queue Filter:</span>
          {(['ALL', 'PENDING_REVIEW', 'APPROVED', 'CHANGES_REQUESTED'] as const).map((filter) => (
            <button
              key={filter}
              onClick={() => setStatusFilter(filter)}
              className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
                statusFilter === filter
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white'
              }`}
            >
              {filter === 'ALL'
                ? 'All Submissions'
                : filter === 'PENDING_REVIEW'
                ? 'Review Queue (Pending)'
                : filter === 'APPROVED'
                ? 'Approved'
                : 'Changes Requested'}
            </button>
          ))}
        </div>

        {/* History selector */}
        <div className="flex items-center gap-2 min-w-[280px]">
          <History className="h-4 w-4 text-slate-400" />
          <select
            id="compliance-history-select"
            className={`${input} py-1.5 text-xs`}
            value={current?.id ?? ''}
            onChange={async (e) => {
              if (!e.target.value) return;
              setBusy(true);
              try {
                const sub = await apiRequest<Submission>(`${base}/compliance/submissions/${e.target.value}`);
                setCurrent(sub);
                setText(sub.content_text);
                setTitle(sub.title);
                setKitId(sub.brand_kit_id);
              } finally {
                setBusy(false);
              }
            }}
          >
            {history.length === 0 && <option value="">No submissions in queue</option>}
            {history.map((h) => (
              <option key={h.id} value={h.id}>
                {h.title} (Rev {h.revision_number} — {h.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Revisions Lineage Bar */}
      {current?.all_revisions && current.all_revisions.length > 1 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5 flex flex-wrap items-center gap-3">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Revision Lineage:</span>
          {current.all_revisions.map((rev) => (
            <button
              key={rev.id}
              onClick={async () => {
                setBusy(true);
                try {
                  const sub = await apiRequest<Submission>(`${base}/compliance/submissions/${rev.id}`);
                  setCurrent(sub);
                  setText(sub.content_text);
                  setTitle(sub.title);
                } finally {
                  setBusy(false);
                }
              }}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-semibold transition-all ${
                rev.id === current.id
                  ? 'bg-indigo-600 text-white ring-2 ring-indigo-400 shadow-md'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              <span>Revision {rev.revision_number}</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded font-bold ${STATUS_COLOUR[rev.status] ?? ''}`}>
                {rev.status}
              </span>
              {rev.score !== null && <span className="text-slate-400 font-mono">({rev.score}/100)</span>}
            </button>
          ))}
        </div>
      )}

      {/* Input Box */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4 shadow-xl">
        <div className="grid md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Target Brand Kit</label>
            <select id="compliance-kit-select" className={input} value={kitId} onChange={(e) => setKitId(e.target.value)}>
              {kits.length === 0 && <option value="">No Brand Kits found — create one in Brand Hub</option>}
              {kits.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Campaign / Submission Title</label>
            <input
              className={input}
              placeholder="e.g. Q4 Retail Wealth Campaign"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Marketing Copy</label>
          <textarea
            className={`${input} h-40 font-mono text-xs md:text-sm`}
            placeholder="Paste or type marketing copy here to check against brand rules..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div className="flex flex-wrap gap-3">
            {canSubmit && (
              <button
                disabled={busy || !kitId || !text.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/30 hover:bg-indigo-500 disabled:opacity-50 transition-all"
                onClick={() =>
                  call(
                    () =>
                      apiRequest<Submission>(`${base}/compliance/submissions`, {
                        method: 'POST',
                        body: JSON.stringify({
                          brand_kit_id: kitId,
                          title: title || 'Untitled content',
                          content_text: text,
                        }),
                      }),
                    'New submission created and analysed.',
                  )
                }
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
                <span>Run Compliance Check (New Submission)</span>
              </button>
            )}

            {canSubmit && current && (
              <button
                disabled={busy || !text.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-slate-800 border border-slate-700 px-4 py-2.5 text-sm font-semibold text-slate-200 hover:bg-slate-700 disabled:opacity-50 transition-all"
                onClick={() =>
                  call(
                    () =>
                      apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/revisions`, {
                        method: 'POST',
                        body: JSON.stringify({ content_text: text }),
                      }),
                    'Saved new revision and re-evaluated.',
                  )
                }
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock className="h-4 w-4" />}
                <span>Save Edit as New Revision</span>
              </button>
            )}
          </div>

          <span className="text-xs text-slate-500">Character count: {text.length} / 50,000</span>
        </div>
      </div>

      {/* Human Review & Approval Action Cards */}
      {current && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-5 shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Approval Status:</span>
              <span
                id="submission-status-badge"
                className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1 text-xs font-bold uppercase tracking-wider ${
                  STATUS_COLOUR[current.status] ?? STATUS_COLOUR.DRAFT
                }`}
              >
                {current.status === 'APPROVED' && <CheckCircle2 className="h-3.5 w-3.5" />}
                {current.status === 'PENDING_REVIEW' && <Clock className="h-3.5 w-3.5" />}
                {current.status === 'CHANGES_REQUESTED' && <RotateCcw className="h-3.5 w-3.5" />}
                {current.status === 'REJECTED' && <XCircle className="h-3.5 w-3.5" />}
                <span>{current.status}</span>
              </span>

              {current.assigned_reviewer_name && (
                <span className="text-xs text-slate-400 flex items-center gap-1 bg-slate-800/80 px-2.5 py-1 rounded-lg">
                  <UserCheck className="h-3.5 w-3.5 text-indigo-400" />
                  <span>Assigned: <strong className="text-white">{current.assigned_reviewer_name}</strong></span>
                </span>
              )}

              {current.reviewed_by_name && (
                <span className="text-xs text-slate-400 flex items-center gap-1 bg-slate-800/80 px-2.5 py-1 rounded-lg">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Decided by: <strong className="text-white">{current.reviewed_by_name}</strong></span>
                </span>
              )}
            </div>

            {/* Author Action: Submit for approval */}
            {canSubmit && current.status !== 'APPROVED' && (
              <div className="flex items-center gap-2">
                <button
                  id="btn-submit-for-approval"
                  disabled={busy}
                  onClick={() => setShowSubmitModal(!showSubmitModal)}
                  className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-md hover:bg-indigo-500 disabled:opacity-50 transition-all"
                >
                  <Send className="h-3.5 w-3.5" />
                  <span>{current.status === 'CHANGES_REQUESTED' ? 'Resubmit for Review' : 'Submit for Human Approval'}</span>
                </button>
              </div>
            )}
          </div>

          {/* Submitter note modal / dropdown */}
          {showSubmitModal && (
            <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4 space-y-3">
              <h3 className="text-xs font-semibold text-indigo-300 uppercase tracking-wider">
                Submit Content for Reviewer Approval
              </h3>
              <div className="grid md:grid-cols-2 gap-3">
                <input
                  className={input}
                  placeholder="Note for reviewer (e.g. Addressed disclaimer comments)..."
                  value={submitComment}
                  onChange={(e) => setSubmitComment(e.target.value)}
                />
                {reviewers.length > 0 && (
                  <select
                    className={input}
                    value={selectedReviewerId}
                    onChange={(e) => setSelectedReviewerId(e.target.value)}
                  >
                    <option value="">Auto-assign or select reviewer...</option>
                    {reviewers.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.full_name} ({r.role})
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  call(
                    async () => {
                      const res = await apiRequest<Submission>(
                        `${base}/compliance/submissions/${current.id}/submit-for-approval`,
                        {
                          method: 'POST',
                          body: JSON.stringify({
                            comments: submitComment || undefined,
                            assigned_reviewer_id: selectedReviewerId || undefined,
                          }),
                        },
                      );
                      setShowSubmitModal(false);
                      setSubmitComment('');
                      return res;
                    },
                    'Submitted for human review successfully.',
                  )
                }
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 transition-colors"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Confirm Submission</span>
              </button>
            </div>
          )}

          {/* Reviewer Decision Panel (Requires approval:decide permission) */}
          {canDecide && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                  <span>Reviewer Action Center</span>
                </h3>

                {/* Reviewer Assignment selector */}
                {reviewers.length > 0 && (
                  <div className="flex items-center gap-2">
                    <select
                      className={`${input} py-1 text-xs`}
                      value={selectedReviewerId || current.assigned_reviewer_id || ''}
                      onChange={(e) => setSelectedReviewerId(e.target.value)}
                    >
                      <option value="">Select Reviewer...</option>
                      {reviewers.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.full_name} ({r.role})
                        </option>
                      ))}
                    </select>
                    <button
                      id="btn-assign-reviewer"
                      disabled={busy || !selectedReviewerId}
                      onClick={() =>
                        call(
                          () =>
                            apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/assign-reviewer`, {
                              method: 'POST',
                              body: JSON.stringify({ reviewer_id: selectedReviewerId }),
                            }),
                          'Reviewer assigned successfully.',
                        )
                      }
                      className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-700 disabled:opacity-50"
                    >
                      Assign
                    </button>
                  </div>
                )}
              </div>

              <textarea
                id="reviewer-comment-input"
                className={`${input} h-20 text-xs`}
                placeholder="Enter review decision notes, feedback, required amendments, or rationale..."
                value={reviewerComment}
                onChange={(e) => setReviewerComment(e.target.value)}
              />

              <div className="flex flex-wrap items-center gap-3">
                <button
                  id="btn-approve-content"
                  disabled={busy}
                  onClick={() =>
                    call(
                      () =>
                        apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/decide`, {
                          method: 'POST',
                          body: JSON.stringify({ decision: 'APPROVE', comments: reviewerComment || undefined }),
                        }),
                      'Content approved for publication.',
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 shadow-md shadow-emerald-600/20 disabled:opacity-50 transition-colors"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Approve Content</span>
                </button>

                <button
                  id="btn-request-revisions"
                  disabled={busy}
                  onClick={() =>
                    call(
                      () =>
                        apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/decide`, {
                          method: 'POST',
                          body: JSON.stringify({ decision: 'REQUEST_CHANGES', comments: reviewerComment || undefined }),
                        }),
                      'Revisions requested from author.',
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-amber-600 px-4 py-2 text-xs font-bold text-white hover:bg-amber-500 shadow-md shadow-amber-600/20 disabled:opacity-50 transition-colors"
                >
                  <RotateCcw className="h-4 w-4" />
                  <span>Request Revisions</span>
                </button>

                <button
                  id="btn-reject-content"
                  disabled={busy}
                  onClick={() =>
                    call(
                      () =>
                        apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/decide`, {
                          method: 'POST',
                          body: JSON.stringify({ decision: 'REJECT', comments: reviewerComment || undefined }),
                        }),
                      'Content rejected.',
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-500 shadow-md shadow-rose-600/20 disabled:opacity-50 transition-colors"
                >
                  <XCircle className="h-4 w-4" />
                  <span>Reject Content</span>
                </button>

                <button
                  id="btn-add-comment"
                  disabled={busy || !reviewerComment.trim()}
                  onClick={() =>
                    call(
                      () =>
                        apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/comments`, {
                          method: 'POST',
                          body: JSON.stringify({ comments: reviewerComment }),
                        }),
                      'Comment recorded in discussion trail.',
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700 disabled:opacity-50 transition-colors ml-auto"
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  <span>Post Note</span>
                </button>
              </div>
            </div>
          )}

          {/* Review Discussion & Audit History Timeline */}
          {current.review_history && current.review_history.length > 0 && (
            <div className="space-y-3 pt-2">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <History className="h-3.5 w-3.5" />
                <span>Review History & Discussion ({current.review_history.length})</span>
              </h3>
              <div className="space-y-2">
                {current.review_history.map((action) => (
                  <div
                    key={action.id}
                    className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3 text-xs space-y-1.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white">{action.actor_name ?? 'System'}</span>
                        <span className="text-slate-500 font-mono">({action.action})</span>
                      </div>
                      <span className="text-[11px] text-slate-500 font-mono">
                        {new Date(action.created_at).toLocaleString()}
                      </span>
                    </div>
                    {action.comments && (
                      <p className="text-slate-300 bg-slate-900/60 p-2 rounded-lg border border-slate-800/60 italic">
                        "{action.comments}"
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Analysis Results View */}
      {current && analysis && (
        <div className="space-y-6">
          {/* Summary Score Card */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div className="flex items-center gap-4">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-bold tracking-wide uppercase ${
                    analysis.result === 'PASS'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                  }`}
                >
                  {analysis.result === 'PASS' ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                  <span>{analysis.result}</span>
                </span>

                <div className="flex items-baseline gap-1.5">
                  <span className="text-4xl font-extrabold text-white tracking-tight">{analysis.score}</span>
                  <span className="text-sm font-semibold text-slate-400">/ 100</span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-xs font-medium text-slate-400 bg-slate-800/80 rounded-lg px-3 py-1.5">
                  Revision {current.revision_number} · {analysis.rules_evaluated} Rules Evaluated
                </span>

                {canSubmit && fixable && (
                  <button
                    disabled={busy}
                    className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-emerald-600/30 hover:bg-emerald-500 disabled:opacity-50 transition-all"
                    onClick={() =>
                      call(
                        () =>
                          apiRequest<Submission>(`${base}/compliance/submissions/${current.id}/apply-corrections`, {
                            method: 'POST',
                            body: JSON.stringify({}),
                          }),
                        'Applied suggested fixes and generated new revision.',
                      )
                    }
                  >
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    <span>Apply Suggested Corrections</span>
                  </button>
                )}
              </div>
            </div>

            {/* Transparent formula & scoring breakdown */}
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
              <p>
                <strong className="text-slate-300">Scoring:</strong> {analysis.scoring.formula}. {analysis.scoring.pass_rule}.
              </p>
              <div className="flex gap-2">
                {analysis.scoring.breakdown
                  .filter((b) => b.count > 0)
                  .map((b) => (
                    <span key={b.severity} className={`rounded px-2 py-0.5 text-[11px] font-semibold ${SEV_COLOUR[b.severity]}`}>
                      {b.count}× {b.severity} (−{b.penalty_total})
                    </span>
                  ))}
              </div>
            </div>

            {/* Highlighted Text Preview */}
            <div className="space-y-1.5 pt-2">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Highlighted Content Preview</span>
              <HighlightedText text={current.content_text} findings={analysis.findings} />
            </div>
          </div>

          {/* Finding Cards */}
          <div className="space-y-3">
            <h2 className="text-lg font-bold text-white tracking-tight flex items-center justify-between">
              <span>Detailed Compliance Findings ({analysis.findings.length})</span>
              {analysis.findings.length === 0 && (
                <span className="text-xs font-normal text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5" /> All rules satisfied!
                </span>
              )}
            </h2>

            {analysis.findings.map((f) => (
              <div
                key={f.finding_id}
                className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-2.5 shadow-md hover:border-slate-700 transition-colors"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`rounded-md px-2.5 py-0.5 text-xs font-bold ${SEV_COLOUR[f.severity]}`}>
                      {f.severity}
                    </span>
                    <span className="font-mono text-xs text-indigo-400 font-semibold">{f.rule_code}</span>
                    <span className="text-sm font-semibold text-white">{f.rule_title}</span>
                  </div>

                  <span className="text-xs text-slate-400 font-mono">
                    {f.start !== null && f.end !== null ? `Positions: chars ${f.start}–${f.end}` : 'Missing Required Element'}
                  </span>
                </div>

                {f.matched_text && (
                  <div className="text-xs text-slate-300">
                    <span className="text-slate-400">Matched Violation:</span>{' '}
                    <code className="rounded bg-rose-950/80 border border-rose-800/80 px-2 py-0.5 font-bold text-rose-200">
                      "{f.matched_text}"
                    </code>
                  </div>
                )}

                {f.evidence_excerpt && (
                  <div className="text-xs text-slate-400 italic bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                    <span className="text-slate-500 font-semibold not-italic">Context Evidence:</span> "{f.evidence_excerpt}"
                  </div>
                )}

                <p className="text-sm text-slate-300">{f.explanation}</p>

                <div className="text-xs text-emerald-300 font-medium bg-emerald-950/30 border border-emerald-800/40 p-2.5 rounded-lg flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                  <span>
                    <strong>Recommended Action:</strong> {f.recommended_correction}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Unified Diff Comparison */}
          {current.comparison && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4 shadow-xl">
              <h2 className="text-lg font-bold text-white tracking-tight flex items-center justify-between">
                <span>Revision Comparison (Original vs Corrected)</span>
                <span className="text-xs text-slate-400 font-normal">
                  Score:{' '}
                  <span className="text-rose-400 font-semibold">{current.comparison.score_before}</span> →{' '}
                  <span className="text-emerald-400 font-semibold">{current.comparison.score_after}</span>{' '}
                  ({current.comparison.score_delta >= 0 ? `+${current.comparison.score_delta}` : current.comparison.score_delta})
                </span>
              </h2>

              <div className="flex flex-wrap gap-4 text-xs">
                <span className="rounded-md bg-emerald-500/10 border border-emerald-500/30 px-3 py-1.5 text-emerald-300">
                  Resolved: {current.comparison.resolved_findings.length} violations
                </span>
                <span className="rounded-md bg-amber-500/10 border border-amber-500/30 px-3 py-1.5 text-amber-300">
                  Remaining: {current.comparison.remaining_findings.length}
                </span>
                <span className="rounded-md bg-rose-500/10 border border-rose-500/30 px-3 py-1.5 text-rose-300">
                  New: {current.comparison.new_findings.length}
                </span>
              </div>

              <pre className="overflow-x-auto rounded-xl bg-slate-950 p-4 font-mono text-xs leading-5 border border-slate-800">
                {current.comparison.text_diff.map((line, i) => (
                  <div
                    key={i}
                    className={
                      line.startsWith('+') && !line.startsWith('+++')
                        ? 'text-emerald-300 bg-emerald-950/20'
                        : line.startsWith('-') && !line.startsWith('---')
                        ? 'text-rose-300 bg-rose-950/20'
                        : 'text-slate-400'
                    }
                  >
                    {line}
                  </div>
                ))}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ComplianceWorkbenchPage;
