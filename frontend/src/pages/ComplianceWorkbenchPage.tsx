import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Clock,
  Cpu,
  FileCheck2,
  HelpCircle,
  History,
  Info,
  Loader2,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Wand2,
  XCircle,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import {
  analyzeContentSubmission,
  applySubmissionCorrections,
  apiRequest,
  submitSubmissionForApproval,
} from '../services/api';
import {
  ComplianceFinding,
  ComplianceScoring,
} from '../types';

interface Analysis {
  score: number;
  result: 'PASS' | 'FAIL';
  rules_evaluated: number;
  findings: ComplianceFinding[];
  scoring: ComplianceScoring;
}

interface Comparison {
  score_before: number;
  score_after: number;
  score_delta: number;
  result_before: string;
  result_after: string;
  resolved_findings: ComplianceFinding[];
  remaining_findings: ComplianceFinding[];
  new_findings: ComplianceFinding[];
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
  submitted_by_user_id: string | null;
  submitted_by_name: string | null;
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
  WARNING: 'bg-amber-500/20 text-amber-300 border border-amber-500/40',
  SUGGESTION: 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40',
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
  WARNING: 'bg-amber-500/40 text-white font-medium border-b-2 border-amber-400',
  SUGGESTION: 'bg-indigo-500/40 text-white font-medium',
};

const input =
  'w-full rounded-xl bg-slate-950 border border-slate-700 px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none';

const DEMO_VIOLATION_SAMPLE =
  'Welcome to the new investment fund. We offer guaranteed returns and a 100% risk-free portfolio for all retail investors. Start investing today!';

const DEMO_HYBRID_SAMPLE =
  'Our Starter Plan is priced at ₹99 / month. We offer guaranteed returns and revolutionary quantum-grade returns that outperform every market benchmark by 800% without any risk.';

const HighlightedText: React.FC<{ text: string; findings: ComplianceFinding[] }> = ({ text, findings }) => {
  const spans = findings
    .filter((f) => f.start !== null && f.end !== null)
    .sort((a, b) => (a.start as number) - (b.start as number));

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach((f, idx) => {
    const s = f.start as number;
    const e = f.end as number;
    if (s < cursor) return;
    parts.push(text.slice(cursor, s));
    parts.push(
      <mark
        key={f.id || f.finding_id || `span-${idx}`}
        title={`${f.rule_code}: ${f.explanation}`}
        className={`rounded px-1.5 py-0.5 ${MARK_COLOUR[f.severity] ?? 'bg-indigo-500/30 text-white'}`}
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
  const { user, activeOrganisationId: orgId, hasPermission } = useAuth();
  const canSubmit = hasPermission('content:create');
  const canDecide = hasPermission('approval:decide');
  const canReview = hasPermission('content:review');

  const [kits, setKits] = useState<Kit[]>([]);
  const [kitId, setKitId] = useState('');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [analysisMode, setAnalysisMode] = useState<'hybrid' | 'deterministic'>('hybrid');
  const [includeExperimentalScore, setIncludeExperimentalScore] = useState(false);
  const [findingsFilter, setFindingsFilter] = useState<'ALL' | 'RULES' | 'EVIDENCE' | 'UNVERIFIED'>('ALL');

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
  const [busyStep, setBusyStep] = useState<string | null>(null);
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
    async (fn: () => Promise<Submission>, successMessage?: string, stepText?: string) => {
      setBusy(true);
      setBusyStep(stepText || 'Executing compliance analysis...');
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
        setBusyStep(null);
      }
    },
    [base],
  );

  // Analysis executor connecting directly to POST /compliance/submissions/analyze
  const handleRunAnalysis = useCallback(async () => {
    if (!orgId || !kitId || !text.trim()) return;
    await call(
      () =>
        analyzeContentSubmission(orgId, {
          brand_kit_id: kitId,
          title: title.trim() || 'Marketing Campaign Review',
          content_text: text.trim(),
          mode: analysisMode,
          include_experimental_score: includeExperimentalScore,
        }),
      analysisMode === 'hybrid'
        ? 'Hybrid compliance review completed.'
        : 'Deterministic compliance review completed.',
      analysisMode === 'hybrid'
        ? 'Running 11-stage LangGraph review (Rules + Vector Retrieval + Grounding)...'
        : 'Evaluating deterministic rule patterns & price integrity...',
    );
  }, [analysisMode, call, includeExperimentalScore, kitId, orgId, text, title]);

  const analysis = current?.analysis ?? null;
  const scoring = analysis?.scoring ?? null;
  const semantic = scoring?.semantic_assessment ?? null;

  const fixable = useMemo(
    () =>
      analysis?.findings.some(
        (f) =>
          (f.correction && (f.correction.replacement !== null || f.correction.append_text)) ||
          f.suggested_replacement,
      ) ?? false,
    [analysis],
  );

  // Filtered findings list
  const filteredFindings = useMemo(() => {
    if (!analysis?.findings) return [];
    if (findingsFilter === 'RULES') {
      return analysis.findings.filter(
        (f) => f.kind !== 'UNVERIFIED_CLAIM' && f.kind !== 'VERIFIED_FACT' && f.source !== 'RAG_SEMANTIC',
      );
    }
    if (findingsFilter === 'EVIDENCE') {
      return analysis.findings.filter((f) => Boolean(f.citation));
    }
    if (findingsFilter === 'UNVERIFIED') {
      return analysis.findings.filter(
        (f) => f.kind === 'UNVERIFIED_CLAIM' || f.rule_type === 'UNVERIFIED_CLAIM' || f.status === 'UNVERIFIED',
      );
    }
    return analysis.findings;
  }, [analysis?.findings, findingsFilter]);

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-semibold text-indigo-300 mb-2">
            <Sparkles className="h-3.5 w-3.5" />
            <span>Phase 6 Compliance Review Workbench</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2.5">
            <FileCheck2 className="h-7 w-7 text-indigo-400" />
            <span>Compliance Review & Evidence Workbench</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Authoritative deterministic rule validation, tenant-isolated vector retrieval, evidence citations, and human approval queue.
          </p>
        </div>

        {/* Demo Samples for Judges & Reviewers */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              setText(DEMO_VIOLATION_SAMPLE);
              setTitle('Acme Wealth Banned Phrase Demo');
              setAnalysisMode('deterministic');
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs font-semibold text-indigo-300 hover:bg-indigo-500/20 transition-colors"
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            <span>Banned Term Sample</span>
          </button>

          <button
            onClick={() => {
              setText(DEMO_HYBRID_SAMPLE);
              setTitle('Acme RAG Grounding & Unverified Guard Demo');
              setAnalysisMode('hybrid');
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 transition-colors"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span>Hybrid RAG Sample</span>
          </button>
        </div>
      </div>

      {/* Global Error Banner with Retry */}
      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <XCircle className="h-5 w-5 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={handleRunAnalysis}
            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600/30 border border-rose-500/40 px-3 py-1 text-xs font-semibold text-rose-200 hover:bg-rose-600/40 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Retry Analysis</span>
          </button>
        </div>
      )}

      {/* Global Notice Banner */}
      {notice && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200 flex items-start gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
          <span>{notice}</span>
        </div>
      )}

      {/* Queue Filter Bar & Submission History */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Queue:</span>
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
                ? 'Pending Review'
                : filter === 'APPROVED'
                ? 'Approved'
                : 'Changes Requested'}
            </button>
          ))}
        </div>

        {/* History selector */}
        <div className="flex items-center gap-2 min-w-[300px]">
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

      {/* Revision Lineage Bar */}
      {current?.all_revisions && current.all_revisions.length > 1 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5 flex flex-wrap items-center gap-3">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Revisions:</span>
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

      {/* Analysis Configuration & Input Card */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4 shadow-xl">
        <div className="grid md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Target Brand Kit</label>
            <select
              id="compliance-kit-select"
              className={input}
              value={kitId}
              onChange={(e) => setKitId(e.target.value)}
            >
              {kits.length === 0 && <option value="">No Brand Kits found — create one in Brand Hub</option>}
              {kits.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Campaign / Submission Title
            </label>
            <input
              className={input}
              placeholder="e.g. Q4 Retail Wealth Campaign"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
        </div>

        {/* Execution Mode Selector */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <Cpu className="h-4 w-4 text-indigo-400" />
              <span>Analysis Mode Selection</span>
            </span>
            <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-400 hover:text-slate-200">
              <input
                type="checkbox"
                checked={includeExperimentalScore}
                onChange={(e) => setIncludeExperimentalScore(e.target.checked)}
                className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-indigo-500"
              />
              <span>Include Experimental Semantic Penalty in Telemetry</span>
            </label>
          </div>

          <div className="grid sm:grid-cols-2 gap-3 pt-1">
            <button
              type="button"
              onClick={() => setAnalysisMode('hybrid')}
              className={`p-3.5 rounded-xl border text-left transition-all ${
                analysisMode === 'hybrid'
                  ? 'border-indigo-500 bg-indigo-950/30 ring-1 ring-indigo-500'
                  : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center gap-2">
                <Sparkles
                  className={`h-4 w-4 ${analysisMode === 'hybrid' ? 'text-indigo-400' : 'text-slate-400'}`}
                />
                <span
                  className={`text-xs font-bold ${
                    analysisMode === 'hybrid' ? 'text-white' : 'text-slate-300'
                  }`}
                >
                  Hybrid Review (Rules + Vector RAG)
                </span>
                <span className="ml-auto text-[10px] font-semibold uppercase bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded">
                  Recommended
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
                Runs 11-stage LangGraph workflow: deterministic rule gate, claim extraction, 1024-dim guideline chunk retrieval, fact verification, brand voice audit, and strict Unverified Guard.
              </p>
            </button>

            <button
              type="button"
              onClick={() => setAnalysisMode('deterministic')}
              className={`p-3.5 rounded-xl border text-left transition-all ${
                analysisMode === 'deterministic'
                  ? 'border-indigo-500 bg-indigo-950/30 ring-1 ring-indigo-500'
                  : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center gap-2">
                <ShieldCheck
                  className={`h-4 w-4 ${
                    analysisMode === 'deterministic' ? 'text-indigo-400' : 'text-slate-400'
                  }`}
                />
                <span
                  className={`text-xs font-bold ${
                    analysisMode === 'deterministic' ? 'text-white' : 'text-slate-300'
                  }`}
                >
                  Deterministic Engine Only
                </span>
                <span className="ml-auto text-[10px] font-semibold uppercase bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                  Fast
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
                Strict rule-based compliance check: banned phrases, required disclaimers, terminology, and approved pricing facts. Zero AI calls or external latencies.
              </p>
            </button>
          </div>
        </div>

        {/* Marketing Copy Textarea */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Marketing Content Copy
            </label>
            <span className="text-[11px] text-slate-500 font-mono">
              {text.length.toLocaleString()} / 50,000 characters
            </span>
          </div>
          <textarea
            className={`${input} h-40 font-mono text-xs md:text-sm`}
            placeholder="Paste or write marketing text here to run compliance and guideline verification..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div className="flex flex-wrap items-center gap-3">
            {canSubmit && (
              <button
                disabled={busy || !kitId || !text.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/30 hover:bg-indigo-500 disabled:opacity-50 transition-all"
                onClick={handleRunAnalysis}
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
                <span>
                  {analysisMode === 'hybrid' ? 'Run Hybrid AI Analysis' : 'Run Deterministic Analysis'}
                </span>
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
                    'Creating revision and evaluating rules...',
                  )
                }
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock className="h-4 w-4" />}
                <span>Save Edit as New Revision</span>
              </button>
            )}
          </div>

          {busyStep && (
            <div className="flex items-center gap-2 text-xs text-indigo-300 font-medium">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>{busyStep}</span>
            </div>
          )}
        </div>
      </div>

      {/* Execution Mode & Fallback Telemetry Banner */}
      {analysis && scoring && (
        <>
          {scoring.engine_mode === 'DETERMINISTIC_FALLBACK' && (
            <div className="rounded-2xl border border-amber-500/40 bg-amber-950/20 p-5 space-y-3">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold text-amber-200 uppercase tracking-wide">
                      Deterministic Fallback Engaged
                    </h3>
                    <span className="text-[10px] font-bold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/40 px-2 py-0.5 rounded">
                      Safe Mode
                    </span>
                  </div>
                  <p className="text-xs text-amber-300/90 leading-relaxed">
                    {scoring.ai_status_message ||
                      'Semantic review bypassed: AI provider unconfigured or unreachable. Deterministic rule analysis displayed normally.'}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3 pt-1 text-xs">
                <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 text-amber-300 font-mono">
                  <CheckCircle2 className="h-3.5 w-3.5 text-amber-400" />
                  Deterministic Score Preserved: {analysis.score}/100
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 text-amber-300 font-mono">
                  <ShieldCheck className="h-3.5 w-3.5 text-amber-400" />
                  Fabricated Findings: 0
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 text-amber-300 font-mono">
                  <HelpCircle className="h-3.5 w-3.5 text-amber-400" />
                  AI Availability: Offline
                </span>
              </div>
            </div>
          )}

          {scoring.engine_mode === 'HYBRID' && (
            <div className="rounded-2xl border border-emerald-500/30 bg-emerald-950/15 p-5 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Sparkles className="h-5 w-5 text-emerald-400 shrink-0" />
                  <div>
                    <h3 className="text-sm font-bold text-emerald-200 uppercase tracking-wide">
                      Hybrid AI Review Completed
                    </h3>
                    <p className="text-xs text-emerald-300/80">
                      Evaluated across 11 LangGraph stages with tenant-isolated 1024-dim guideline vector retrieval.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-0.5 rounded-full">
                    <CheckCircle2 className="h-3 w-3" />
                    AI Provider Active
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2.5 py-0.5 rounded-full font-mono">
                    {scoring.node_trace?.length ?? 11} Stages
                  </span>
                </div>
              </div>

              {scoring.node_trace && scoring.node_trace.length > 0 && (
                <div className="pt-1 flex flex-wrap items-center gap-1.5 text-[10px] font-mono text-slate-400">
                  <span className="text-slate-500 font-sans font-semibold">Workflow Trace:</span>
                  {scoring.node_trace.map((node, i) => (
                    <React.Fragment key={node}>
                      <span className="bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5 text-slate-300">
                        {node}
                      </span>
                      {i < (scoring.node_trace?.length ?? 0) - 1 && <span className="text-slate-600">→</span>}
                    </React.Fragment>
                  ))}
                </div>
              )}
            </div>
          )}

          {scoring.engine_mode === 'DETERMINISTIC' && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2 text-slate-300">
                <ShieldCheck className="h-4 w-4 text-indigo-400" />
                <span>
                  <strong>Deterministic Mode:</strong> Rule pattern matching, price integrity, and disclaimer checks.
                </span>
              </div>
              <span className="text-slate-500 font-mono">Pass Threshold: 70/100</span>
            </div>
          )}
        </>
      )}

      {/* Human Review & Approval Action Cards */}
      {current && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-5 shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Approval Status:
              </span>
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
                  <span>
                    Assigned: <strong className="text-white">{current.assigned_reviewer_name}</strong>
                  </span>
                </span>
              )}

              {current.reviewed_by_name && (
                <span className="text-xs text-slate-400 flex items-center gap-1 bg-slate-800/80 px-2.5 py-1 rounded-lg">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                  <span>
                    Decided by: <strong className="text-white">{current.reviewed_by_name}</strong>
                  </span>
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
                  <span>
                    {current.status === 'CHANGES_REQUESTED' ? 'Resubmit for Review' : 'Submit for Human Approval'}
                  </span>
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
                {(() => {
                  const eligibleReviewers = reviewers.filter((r) => r.id !== user?.id);
                  return (
                    <div className="flex flex-col gap-1">
                      <select
                        className={input}
                        value={selectedReviewerId}
                        onChange={(e) => setSelectedReviewerId(e.target.value)}
                      >
                        <option value="">Auto-assign or select reviewer...</option>
                        {eligibleReviewers.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.full_name} ({r.role})
                          </option>
                        ))}
                      </select>
                      {eligibleReviewers.length === 0 && (
                        <span className="text-[11px] text-amber-400">
                          No other eligible reviewers available. Invite an independent reviewer.
                        </span>
                      )}
                    </div>
                  );
                })()}
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  call(
                    async () => {
                      const res = await submitSubmissionForApproval(
                        orgId!,
                        current.id,
                        submitComment || null,
                        selectedReviewerId || null,
                      );
                      setShowSubmitModal(false);
                      setSubmitComment('');
                      setSelectedReviewerId('');
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
              {current.submitted_by_user_id === user?.id && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300 flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                  <span>Independent review required: You submitted this copy.</span>
                </div>
              )}

              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                  <span>Reviewer Action Center</span>
                </h3>

                {/* Reviewer Assignment selector */}
                {(() => {
                  const eligibleReviewers = reviewers.filter((r) => r.id !== current.submitted_by_user_id);
                  if (eligibleReviewers.length === 0) return null;
                  return (
                    <div className="flex items-center gap-2">
                      <select
                        className={`${input} py-1 text-xs`}
                        value={selectedReviewerId || current.assigned_reviewer_id || ''}
                        onChange={(e) => setSelectedReviewerId(e.target.value)}
                      >
                        <option value="">Select Reviewer...</option>
                        {eligibleReviewers.map((r) => (
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
                  );
                })()}
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
                  disabled={busy || current.submitted_by_user_id === user?.id}
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
                  className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 shadow-md shadow-emerald-600/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Approve Content</span>
                </button>

                <button
                  id="btn-request-revisions"
                  disabled={busy || current.submitted_by_user_id === user?.id}
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
                  className="inline-flex items-center gap-1.5 rounded-xl bg-amber-600 px-4 py-2 text-xs font-bold text-white hover:bg-amber-500 shadow-md shadow-amber-600/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <RotateCcw className="h-4 w-4" />
                  <span>Request Revisions</span>
                </button>

                <button
                  id="btn-reject-content"
                  disabled={busy || current.submitted_by_user_id === user?.id}
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
                  className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-500 shadow-md shadow-rose-600/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
          {/* Dual Score & Telemetry Cards */}
          <div className="grid md:grid-cols-3 gap-6">
            {/* Primary Deterministic Compliance Score (Authoritative) */}
            <div className="md:col-span-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4 shadow-xl">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
                <div className="flex items-center gap-4">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-bold tracking-wide uppercase ${
                      analysis.result === 'PASS'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                        : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                    }`}
                  >
                    {analysis.result === 'PASS' ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <XCircle className="h-4 w-4" />
                    )}
                    <span>{analysis.result}</span>
                  </span>

                  <div className="flex items-baseline gap-1.5">
                    <span className="text-4xl font-extrabold text-white tracking-tight">
                      {analysis.score}
                    </span>
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
                          () => applySubmissionCorrections(orgId!, current.id),
                          'Applied suggested fixes and generated new revision.',
                          'Applying fixes and re-evaluating rules...',
                        )
                      }
                    >
                      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                      <span>Apply Suggested Corrections</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Transparent Formula & Breakdown */}
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                <p>
                  <strong className="text-slate-300">Authoritative Formula:</strong>{' '}
                  {scoring?.formula || '100 - sum(deterministic_penalties)'}. Pass rule: score ≥{' '}
                  {scoring?.pass_threshold ?? 70}.
                </p>
                <div className="flex flex-wrap gap-2">
                  {(scoring?.breakdown ?? [])
                    .filter((b) => b.count > 0)
                    .map((b) => (
                      <span
                        key={b.severity}
                        className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                          SEV_COLOUR[b.severity] ?? ''
                        }`}
                      >
                        {b.count}× {b.severity} (−{b.penalty_total})
                      </span>
                    ))}
                </div>
              </div>

              {/* Highlighted Text Preview */}
              <div className="space-y-1.5 pt-2">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Highlighted Violations & Claims Preview
                </span>
                <HighlightedText text={current.content_text} findings={analysis.findings} />
              </div>
            </div>

            {/* Semantic Assessment Card (Non-Penalizing Telemetry) */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 flex flex-col justify-between shadow-xl space-y-4">
              <div>
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                    <Sparkles className="h-4 w-4 text-indigo-400" />
                    <span>Semantic Assessment</span>
                  </h3>
                  <span className="text-[10px] font-mono text-slate-500 uppercase bg-slate-800 px-2 py-0.5 rounded">
                    Telemetry
                  </span>
                </div>

                <p className="text-[11px] text-slate-400 mt-2">
                  Non-penalizing AI fact grounding and claim verification stats. Does not reduce the authoritative deterministic score.
                </p>

                {semantic ? (
                  <div className="grid grid-cols-2 gap-3 mt-4">
                    <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
                      <span className="text-[11px] text-slate-400">Claims Extracted</span>
                      <div className="text-xl font-bold text-white mt-1">
                        {semantic.claims_extracted}
                      </div>
                    </div>

                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/20 p-3">
                      <span className="text-[11px] text-emerald-400">Verified Facts</span>
                      <div className="text-xl font-bold text-emerald-300 mt-1">
                        {semantic.claims_verified}
                      </div>
                    </div>

                    <div className="rounded-xl border border-rose-500/20 bg-rose-950/20 p-3">
                      <span className="text-[11px] text-rose-400">Contradicted</span>
                      <div className="text-xl font-bold text-rose-300 mt-1">
                        {semantic.claims_contradicted}
                      </div>
                    </div>

                    <div className="rounded-xl border border-amber-500/20 bg-amber-950/20 p-3">
                      <span className="text-[11px] text-amber-400">Unverified Claims</span>
                      <div className="text-xl font-bold text-amber-300 mt-1">
                        {semantic.claims_unverified}
                      </div>
                    </div>

                    <div className="col-span-2 rounded-xl border border-indigo-500/20 bg-indigo-950/20 p-3 flex items-center justify-between">
                      <span className="text-[11px] text-indigo-300">Candidate Guideline Chunks</span>
                      <span className="text-sm font-bold text-white font-mono">
                        {semantic.candidate_chunks_retrieved} retrieved
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 p-4 text-xs text-slate-500 text-center mt-4 space-y-1">
                    <Info className="h-4 w-4 mx-auto text-slate-600" />
                    <p>Semantic assessment unavailable in deterministic mode.</p>
                  </div>
                )}
              </div>

              {scoring?.experimental_score !== undefined && (
                <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-3 text-xs text-slate-300 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-indigo-300 font-semibold">Experimental Score:</span>
                    <span className="font-mono font-bold text-white">
                      {scoring.experimental_score}/100
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400 leading-tight">
                    For research telemetry only. Never affects production pass/fail decision.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Finding Cards with Filter Bar */}
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                <span>Detailed Findings & Evidence Citations</span>
                <span className="text-xs font-normal text-slate-400 bg-slate-800 px-2 py-0.5 rounded-full font-mono">
                  {analysis.findings.length}
                </span>
              </h2>

              {/* Findings Filter */}
              <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 p-1 rounded-xl text-xs">
                <button
                  type="button"
                  onClick={() => setFindingsFilter('ALL')}
                  className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                    findingsFilter === 'ALL'
                      ? 'bg-indigo-600 text-white'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  All ({analysis.findings.length})
                </button>
                <button
                  type="button"
                  onClick={() => setFindingsFilter('RULES')}
                  className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                    findingsFilter === 'RULES'
                      ? 'bg-indigo-600 text-white'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Rule Violations
                </button>
                <button
                  type="button"
                  onClick={() => setFindingsFilter('EVIDENCE')}
                  className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                    findingsFilter === 'EVIDENCE'
                      ? 'bg-indigo-600 text-white'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Grounded Evidence
                </button>
                <button
                  type="button"
                  onClick={() => setFindingsFilter('UNVERIFIED')}
                  className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                    findingsFilter === 'UNVERIFIED'
                      ? 'bg-indigo-600 text-white'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Unverified Claims
                </button>
              </div>
            </div>

            {filteredFindings.length === 0 ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center text-slate-400 space-y-2">
                <CheckCircle2 className="h-8 w-8 mx-auto text-emerald-400" />
                <p className="text-sm font-semibold text-slate-200">No findings matching the selected filter.</p>
                <p className="text-xs text-slate-500">All brand rules and guideline boundaries in this category are satisfied.</p>
              </div>
            ) : (
              filteredFindings.map((f, idx) => {
                const isUnverified =
                  f.kind === 'UNVERIFIED_CLAIM' ||
                  f.rule_type === 'UNVERIFIED_CLAIM' ||
                  f.status === 'UNVERIFIED';
                const hasCitation = Boolean(f.citation);

                return (
                  <div
                    key={f.id || f.finding_id || `finding-${idx}`}
                    className={`rounded-2xl border p-5 space-y-3.5 shadow-md transition-all ${
                      isUnverified
                        ? 'border-amber-500/30 bg-amber-950/10'
                        : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'
                    }`}
                  >
                    {/* Header Row */}
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-md px-2.5 py-0.5 text-xs font-bold ${
                            SEV_COLOUR[f.severity] ?? SEV_COLOUR.INFO
                          }`}
                        >
                          {f.severity}
                        </span>

                        <span className="font-mono text-xs text-indigo-400 font-semibold">
                          {f.rule_code}
                        </span>

                        <span className="text-sm font-semibold text-white">
                          {f.rule_title || f.title || 'Compliance Item'}
                        </span>

                        {f.kind && (
                          <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                            {f.kind}
                          </span>
                        )}
                      </div>

                      <span className="text-xs text-slate-400 font-mono">
                        {f.start !== null && f.end !== null
                          ? `Chars ${f.start}–${f.end}`
                          : 'Global Submission Element'}
                      </span>
                    </div>

                    {/* Matched Text */}
                    {f.matched_text && (
                      <div className="text-xs text-slate-300">
                        <span className="text-slate-400 font-medium">Marketing Copy Excerpt:</span>{' '}
                        <code className="rounded bg-rose-950/80 border border-rose-800/80 px-2 py-0.5 font-bold text-rose-200">
                          "{f.matched_text}"
                        </code>
                      </div>
                    )}

                    {/* Explanation */}
                    <p className="text-sm text-slate-300 leading-relaxed">{f.explanation}</p>

                    {/* Unverified Guard Explicit Callout */}
                    {isUnverified && (
                      <div className="rounded-xl border border-amber-500/40 bg-amber-950/20 p-3.5 space-y-1.5 text-xs">
                        <div className="flex items-center gap-2 font-bold text-amber-300">
                          <ShieldAlert className="h-4 w-4 text-amber-400" />
                          <span>Unverified Guard Notice</span>
                        </div>
                        <p className="text-amber-200/90 leading-relaxed">
                          This marketing claim could not be verified against any approved brand guideline document or fact.
                        </p>
                        <p className="text-[11px] text-amber-300/60">
                          To protect against AI hallucination, any non-matching or boundary-violating citations were rejected by the Unverified Guard.
                        </p>
                      </div>
                    )}

                    {/* Evidence Panel (Chunk Citation) */}
                    {hasCitation && f.citation && (
                      <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4 space-y-2.5">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-indigo-500/20 pb-2">
                          <div className="flex items-center gap-2">
                            <BookOpen className="h-4 w-4 text-indigo-400" />
                            <span className="text-xs font-bold text-white">
                              {f.citation.document_title}
                            </span>
                          </div>

                          <div className="flex flex-wrap items-center gap-2 text-[10px] font-mono">
                            <span className="bg-slate-900 px-2 py-0.5 rounded text-indigo-300 border border-indigo-500/20">
                              Chunk: {f.citation.chunk_id.slice(0, 8)}...
                            </span>
                            {f.citation.page_number && (
                              <span className="bg-slate-900 px-2 py-0.5 rounded text-slate-300 border border-slate-700">
                                Page {f.citation.page_number}
                              </span>
                            )}
                            {f.citation.similarity_score !== undefined && (
                              <span className="bg-emerald-950 px-2 py-0.5 rounded text-emerald-300 border border-emerald-500/30">
                                {Math.round(f.citation.similarity_score * 100)}% match
                              </span>
                            )}
                          </div>
                        </div>

                        <blockquote className="text-xs italic text-indigo-200/90 bg-slate-950/60 p-3 rounded-lg border border-indigo-500/20 leading-relaxed font-mono">
                          "{f.citation.content || f.evidence_excerpt}"
                        </blockquote>

                        <div className="flex items-center gap-2 text-[11px]">
                          <span className="text-slate-400">Grounding Status:</span>
                          <span
                            className={`font-semibold uppercase ${
                              f.status === 'CONTRADICTED' ? 'text-rose-400' : 'text-emerald-400'
                            }`}
                          >
                            {f.status || 'VERIFIED'}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Recommended Action / Correction */}
                    {(f.recommended_correction || f.suggested_replacement) && (
                      <div className="text-xs text-emerald-300 font-medium bg-emerald-950/30 border border-emerald-800/40 p-3 rounded-xl flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                          <span>
                            <strong>Suggested Remediation:</strong>{' '}
                            {f.recommended_correction || f.suggested_replacement}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
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
