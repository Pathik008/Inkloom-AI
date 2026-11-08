import React from 'react';
import { Link } from 'react-router-dom';
import { Clock, ArrowLeft, ShieldCheck } from 'lucide-react';

interface PlannedModulePageProps {
  title: string;
  phase: string;
  owner: string;
  summary: string;
  deliverables: string[];
}

export const PlannedModulePage: React.FC<PlannedModulePageProps> = ({
  title,
  phase,
  owner,
  summary,
  deliverables,
}) => {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-8 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 rounded-full bg-indigo-500/10 border border-indigo-500/30 px-3 py-1 text-xs font-semibold text-indigo-300">
            <Clock className="h-3.5 w-3.5" />
            <span>Scheduled for {phase}</span>
          </span>
          <span className="text-xs text-slate-400">Module Lead: {owner}</span>
        </div>

        <div>
          <h2 className="text-2xl font-bold text-white">{title}</h2>
          <p className="mt-2 text-sm text-slate-300 leading-relaxed">{summary}</p>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <ShieldCheck className="h-4 w-4 text-indigo-400" />
            <span>Planned Engineering Deliverables ({phase})</span>
          </div>
          <ul className="space-y-2 text-xs text-slate-300 list-disc list-inside">
            {deliverables.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="pt-2">
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-medium text-slate-200 hover:border-indigo-500 hover:text-white transition"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Return to Phase 1 System Telemetry</span>
          </Link>
        </div>
      </div>
    </div>
  );
};
