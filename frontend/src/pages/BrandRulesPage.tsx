import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, CheckCircle2, Clock, Plus, Rocket, Trash2, XCircle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { apiRequest } from '../services/api';

interface KitVersionSummary {
  id: string;
  version_number: number;
  status: string;
}

interface KitSummary {
  id: string;
  name: string;
  active_version_id: string | null;
  versions?: KitVersionSummary[];
}

interface Rule {
  id: string;
  rule_code: string;
  rule_type: string;
  severity: string;
  title: string;
  description: string;
  target_pattern: string;
  match_mode: string;
  required_disclaimer_text: string | null;
  suggested_replacement: string | null;
  approval_status: string;
}

const RULE_TYPES: { value: string; label: string }[] = [
  { value: 'PROHIBITED_TERM', label: 'Banned phrase' },
  { value: 'MANDATORY_DISCLAIMER', label: 'Mandatory disclaimer' },
  { value: 'MANDATORY_TERMINOLOGY', label: 'Required terminology' },
  { value: 'RESTRICTED_CLAIM', label: 'Restricted claim' },
  { value: 'PRICE_INTEGRITY', label: 'Price integrity' },
  { value: 'TONE_CONSTRAINT', label: 'Tone constraint' },
];

const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];
const MATCH_MODES = ['CASE_INSENSITIVE', 'WORD_BOUNDARY', 'EXACT', 'REGEX'];

const input = 'w-full rounded-xl bg-slate-950 border border-slate-700 px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none';
const btn = 'inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50 transition-all';

export const BrandRulesPage: React.FC = () => {
  const { activeOrganisationId: orgId, hasPermission } = useAuth();
  const canManage = hasPermission('brand:manage');
  const [kits, setKits] = useState<KitSummary[]>([]);
  const [kitId, setKitId] = useState('');
  const [versions, setVersions] = useState<KitVersionSummary[]>([]);
  const [versionId, setVersionId] = useState('');
  const [rules, setRules] = useState<Rule[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newKit, setNewKit] = useState('');
  const [form, setForm] = useState({
    rule_type: 'PROHIBITED_TERM',
    title: '',
    description: '',
    target_pattern: '',
    severity: 'HIGH',
    match_mode: 'CASE_INSENSITIVE',
    suggested_replacement: '',
    required_disclaimer_text: '',
  });

  const base = `/api/v1/organisations/${orgId}/brand-kits`;
  const version = versions.find((v) => v.id === versionId);
  const isDraft = version?.status === 'DRAFT';

  const run = useCallback(async (fn: () => Promise<void>, ok?: string) => {
    setError(null);
    setNotice(null);
    try {
      await fn();
      if (ok) setNotice(ok);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed');
    }
  }, []);

  const loadKits = useCallback(async () => {
    if (!orgId) return;
    const list = await apiRequest<KitSummary[]>(`${base}`);
    setKits(list);
    setKitId((cur) => (cur && list.some((k) => k.id === cur) ? cur : list[0]?.id || ''));
  }, [base, orgId]);

  const loadVersions = useCallback(async () => {
    if (!orgId || !kitId) {
      setVersions([]);
      setVersionId('');
      return;
    }
    const detail = await apiRequest<{ versions: KitVersionSummary[] }>(`${base}/${kitId}`);
    const vs = [...detail.versions].sort((a, b) => b.version_number - a.version_number);
    setVersions(vs);
    // Automatically select the DRAFT version, or the latest version
    const target = vs.find((v) => v.status === 'DRAFT') ?? vs[0];
    setVersionId(target ? target.id : '');
  }, [base, kitId, orgId]);

  const loadRules = useCallback(async () => {
    if (!orgId || !kitId || !versionId) return setRules([]);
    // Ensure versionId strictly belongs to the currently selected kit
    if (!versions.some((v) => v.id === versionId)) return setRules([]);
    setRules(await apiRequest<Rule[]>(`${base}/${kitId}/versions/${versionId}/rules`));
  }, [base, kitId, orgId, versionId, versions]);

  useEffect(() => {
    void run(loadKits);
  }, [run, loadKits]);

  useEffect(() => {
    void run(loadVersions);
  }, [run, loadVersions]);

  useEffect(() => {
    void run(loadRules);
  }, [run, loadRules]);

  const rulesUrl = `${base}/${kitId}/versions/${versionId}/rules`;
  const pending = useMemo(() => rules.filter((r) => r.approval_status !== 'APPROVED').length, [rules]);

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2.5">
          <BookOpen className="h-7 w-7 text-indigo-400" />
          <span>Brand Hub — Compliance Rules & Knowledge</span>
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Configure deterministic rules on a DRAFT Brand Kit version. Once approved and published, the version becomes strictly immutable and serves as the source of truth for compliance checks.
        </p>
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

      {/* Selectors */}
      <div className="grid md:grid-cols-3 gap-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
        <label className="space-y-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <span>Active Brand Kit</span>
          <select
            id="brand-kit-select"
            className={input}
            value={kitId}
            onChange={(e) => setKitId(e.target.value)}
          >
            {kits.length === 0 && <option value="">No Brand Kits created yet</option>}
            {kits.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <span>Version Selector</span>
          <select
            id="version-select"
            className={input}
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            {versions.length === 0 && <option value="">No versions available</option>}
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version_number} — {v.status}
              </option>
            ))}
          </select>
        </label>

        {canManage && (
          <div className="space-y-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <span>Create New Brand Kit</span>
            <div className="flex gap-2">
              <input
                className={input}
                placeholder="Brand Kit name"
                value={newKit}
                onChange={(e) => setNewKit(e.target.value)}
              />
              <button
                className={`${btn} bg-indigo-600 text-white shrink-0 hover:bg-indigo-500`}
                disabled={newKit.trim().length < 2}
                onClick={() =>
                  run(async () => {
                    const k = await apiRequest<KitSummary>(base, {
                      method: 'POST',
                      body: JSON.stringify({ name: newKit.trim() }),
                    });
                    setNewKit('');
                    setKitId(k.id);
                    if (k.versions && k.versions.length > 0) {
                      setVersions(k.versions);
                      setVersionId(k.versions[0].id);
                    } else {
                      setVersionId('');
                    }
                    await loadKits();
                  }, 'New Brand Kit created with an initial DRAFT version.')
                }
              >
                <Plus className="h-4 w-4" />
                <span>Create</span>
              </button>
            </div>
          </div>
        )}
      </div>

      {kitId && versionId && (
        <>
          {/* Status & Action Bar */}
          <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/40 p-4 rounded-xl border border-slate-800">
            <div className="flex items-center gap-3">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ${
                  version?.status === 'PUBLISHED'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                    : version?.status === 'ARCHIVED'
                    ? 'bg-slate-700/40 text-slate-400 border border-slate-600'
                    : 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40'
                }`}
              >
                {version?.status === 'PUBLISHED' && <CheckCircle2 className="h-3.5 w-3.5" />}
                {version?.status === 'DRAFT' && <Clock className="h-3.5 w-3.5" />}
                <span>{version?.status}</span>
              </span>

              <span className="text-sm text-slate-300 font-medium">
                {rules.length} Rule(s) Configured
                {pending > 0 && <span className="text-amber-400 ml-2 font-semibold">({pending} awaiting review)</span>}
              </span>
            </div>

            <div className="flex items-center gap-3">
              {canManage && isDraft && (
                <button
                  className={`${btn} bg-emerald-600 text-white shadow-lg shadow-emerald-600/30 hover:bg-emerald-500`}
                  onClick={() =>
                    run(async () => {
                      await apiRequest(`${base}/${kitId}/versions/${versionId}/publish`, { method: 'POST' });
                      await loadKits();
                      await loadVersions();
                      await loadRules();
                    }, 'Version published! It is now the active source of truth.')
                  }
                >
                  <Rocket className="h-4 w-4" />
                  <span>Publish Version</span>
                </button>
              )}

              {canManage && version?.status === 'PUBLISHED' && (
                <button
                  className={`${btn} bg-slate-800 border border-slate-700 text-slate-200 hover:bg-slate-700`}
                  onClick={() =>
                    run(async () => {
                      await apiRequest(`${base}/${kitId}/versions`, { method: 'POST', body: JSON.stringify({}) });
                      await loadVersions();
                    }, 'New sequential DRAFT version created with all rules cloned.')
                  }
                >
                  <Plus className="h-4 w-4" />
                  <span>Create New Draft to Edit Rules</span>
                </button>
              )}
            </div>
          </div>

          {/* Add Rule Form (Only visible on DRAFT) */}
          {canManage && isDraft && (
            <form
              className="grid md:grid-cols-2 gap-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl"
              onSubmit={(e) => {
                e.preventDefault();
                if (!versionId || !versions.some((v) => v.id === versionId)) {
                  setError('Please wait for version to load before adding rules.');
                  return;
                }
                void run(async () => {
                  const body: Record<string, unknown> = {
                    rule_type: form.rule_type,
                    title: form.title,
                    description: form.description,
                    target_pattern: form.target_pattern,
                    severity: form.severity,
                    match_mode: form.match_mode,
                  };
                  if (form.suggested_replacement) body.suggested_replacement = form.suggested_replacement;
                  if (form.required_disclaimer_text) body.required_disclaimer_text = form.required_disclaimer_text;
                  await apiRequest(`${base}/${kitId}/versions/${versionId}/rules`, { method: 'POST', body: JSON.stringify(body) });
                  setForm({
                    ...form,
                    title: '',
                    description: '',
                    target_pattern: '',
                    suggested_replacement: '',
                    required_disclaimer_text: '',
                  });
                  await loadRules();
                }, 'Rule created successfully in PENDING_REVIEW status.');
              }}
            >
              <div className="md:col-span-2 flex items-center justify-between border-b border-slate-800 pb-3">
                <h2 className="text-sm font-bold text-white uppercase tracking-wider">Configure New Rule</h2>
                {/* Pre-fill quick template buttons */}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setForm({
                        rule_type: 'PROHIBITED_TERM',
                        title: 'Guaranteed Returns Prohibition',
                        description: 'Regulations prohibit promising or guaranteeing investment returns.',
                        target_pattern: 'guaranteed returns',
                        severity: 'CRITICAL',
                        match_mode: 'CASE_INSENSITIVE',
                        suggested_replacement: 'potential returns',
                        required_disclaimer_text: '',
                      })
                    }
                    className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
                  >
                    + Template: Banned Phrase
                  </button>
                  <span className="text-slate-600">|</span>
                  <button
                    type="button"
                    onClick={() =>
                      setForm({
                        rule_type: 'MANDATORY_DISCLAIMER',
                        title: 'Market Risk Disclaimer',
                        description: 'Disclose market risk on all investment promotions.',
                        target_pattern: 'market risk',
                        severity: 'HIGH',
                        match_mode: 'CASE_INSENSITIVE',
                        suggested_replacement: '',
                        required_disclaimer_text: 'Investments are subject to market risk. Read all scheme related documents carefully.',
                      })
                    }
                    className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
                  >
                    + Template: Disclaimer
                  </button>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-400">Rule Type</label>
                <select id="rule-type-select" className={input} value={form.rule_type} onChange={(e) => setForm({ ...form, rule_type: e.target.value })}>
                  {RULE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-400">Severity</label>
                  <select id="rule-severity-select" className={input} value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                    {SEVERITIES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-400">Match Mode</label>
                  <select id="rule-match-mode-select" className={input} value={form.match_mode} onChange={(e) => setForm({ ...form, match_mode: e.target.value })}>
                    {MATCH_MODES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-400">Rule Title</label>
                <input
                  required
                  className={input}
                  placeholder="e.g. No Guaranteed Returns"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-400">Target Pattern / Trigger</label>
                <input
                  required
                  className={input}
                  placeholder={form.rule_type === 'MANDATORY_DISCLAIMER' ? 'Trigger keyword (e.g. market risk)' : 'Exact word or phrase'}
                  value={form.target_pattern}
                  onChange={(e) => setForm({ ...form, target_pattern: e.target.value })}
                />
              </div>

              <div className="md:col-span-2 space-y-1.5">
                <label className="text-xs font-semibold text-slate-400">Rule Explanation / Rationale</label>
                <input
                  required
                  className={input}
                  placeholder="Explain why this rule exists (displayed to reviewers in findings)"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>

              {form.rule_type === 'MANDATORY_DISCLAIMER' ? (
                <div className="md:col-span-2 space-y-1.5">
                  <label className="text-xs font-semibold text-slate-400">Mandatory Disclaimer Text</label>
                  <textarea
                    required
                    className={`${input} h-20 font-mono`}
                    placeholder="Enter the exact disclaimer text that must be present in copy..."
                    value={form.required_disclaimer_text}
                    onChange={(e) => setForm({ ...form, required_disclaimer_text: e.target.value })}
                  />
                </div>
              ) : (
                <div className="md:col-span-2 space-y-1.5">
                  <label className="text-xs font-semibold text-slate-400">Suggested Correction / Replacement</label>
                  <input
                    className={input}
                    placeholder="Recommended replacement phrase (e.g. potential returns)"
                    value={form.suggested_replacement}
                    onChange={(e) => setForm({ ...form, suggested_replacement: e.target.value })}
                  />
                </div>
              )}

              <button
                type="submit"
                className={`${btn} bg-indigo-600 text-white md:col-span-2 justify-center hover:bg-indigo-500 shadow-lg shadow-indigo-600/30`}
              >
                <Plus className="h-4 w-4" />
                <span>Add Compliance Rule</span>
              </button>
            </form>
          )}

          {/* Rules List */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 divide-y divide-slate-800 shadow-xl">
            <div className="p-4 bg-slate-950/40 rounded-t-2xl font-bold text-sm text-white flex items-center justify-between">
              <span>Configured Rules ({rules.length})</span>
              <span className="text-xs text-slate-400 font-normal">
                {isDraft ? 'Review and approve rules to publish this version' : 'Rules are locked for this version'}
              </span>
            </div>

            {rules.length === 0 && (
              <p className="p-8 text-center text-sm text-slate-400">No rules have been added to this version yet.</p>
            )}

            {rules.map((r) => (
              <div key={r.id} className="p-5 flex flex-wrap items-start justify-between gap-4 hover:bg-slate-800/20 transition-colors">
                <div className="space-y-1.5 min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-bold text-indigo-400 bg-indigo-950/60 border border-indigo-800/60 rounded px-2 py-0.5">
                      {r.rule_code}
                    </span>
                    <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300 font-medium">
                      {r.rule_type}
                    </span>
                    <span className="rounded bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 text-xs font-semibold text-amber-300">
                      {r.severity}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold ${
                        r.approval_status === 'APPROVED'
                          ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
                          : 'bg-amber-500/10 border border-amber-500/30 text-amber-300'
                      }`}
                    >
                      {r.approval_status === 'APPROVED' ? <CheckCircle2 className="h-3 w-3" /> : <Clock className="h-3 w-3" />}
                      <span>{r.approval_status}</span>
                    </span>
                  </div>

                  <p className="text-base font-semibold text-white tracking-tight">{r.title}</p>
                  <p className="text-xs text-slate-400">
                    Pattern:{' '}
                    <code className="rounded bg-slate-800 px-1.5 py-0.5 font-bold text-slate-200">
                      "{r.target_pattern}"
                    </code>{' '}
                    · Match: <span className="font-medium text-slate-300">{r.match_mode}</span>
                    {r.suggested_replacement && (
                      <span className="text-emerald-400 ml-2 font-medium">
                        → Suggested Fix: "{r.suggested_replacement}"
                      </span>
                    )}
                  </p>
                  {r.required_disclaimer_text && (
                    <p className="text-xs text-slate-400 bg-slate-950/50 p-2 rounded-lg border border-slate-800/80">
                      <strong className="text-slate-300">Required Disclaimer:</strong> "{r.required_disclaimer_text}"
                    </p>
                  )}
                  <p className="text-xs text-slate-400 italic">{r.description}</p>
                </div>

                {canManage && isDraft && (
                  <div className="flex items-center gap-2">
                    {r.approval_status !== 'APPROVED' ? (
                      <button
                        className={`${btn} bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30`}
                        onClick={() =>
                          run(async () => {
                            await apiRequest(`${rulesUrl}/${r.id}/approve`, { method: 'POST' });
                            await loadRules();
                          }, `Rule ${r.rule_code} approved.`)
                        }
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        <span>Approve</span>
                      </button>
                    ) : (
                      <button
                        className={`${btn} bg-amber-600/20 border border-amber-500/40 text-amber-300 hover:bg-amber-600/30`}
                        onClick={() =>
                          run(async () => {
                            await apiRequest(`${rulesUrl}/${r.id}/reject`, { method: 'POST' });
                            await loadRules();
                          }, `Rule ${r.rule_code} moved back to review.`)
                        }
                      >
                        <XCircle className="h-4 w-4" />
                        <span>Reject</span>
                      </button>
                    )}

                    <button
                      className={`${btn} bg-rose-600/20 border border-rose-500/40 text-rose-300 hover:bg-rose-600/30 px-3`}
                      title="Delete rule"
                      onClick={() =>
                        run(async () => {
                          await apiRequest(`${rulesUrl}/${r.id}`, { method: 'DELETE' });
                          await loadRules();
                        }, `Rule ${r.rule_code} deleted.`)
                      }
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default BrandRulesPage;
