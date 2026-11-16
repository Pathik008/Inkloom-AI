import React from 'react';
import { Link } from 'react-router-dom';
import { Clock, ArrowLeft, ArrowRight, ShieldCheck, Sparkles } from 'lucide-react';

interface PlannedModulePageProps {
  title: string;
  phase: string;
  owner: string;
  summary: string;
  deliverables: string[];
  integratedDestinationUrl?: string;
  integratedDestinationLabel?: string;
  integratedDestinationNote?: string;
}

export const PlannedModulePage: React.FC<PlannedModulePageProps> = ({
  title,
  phase,
  owner,
  summary,
  deliverables,
  integratedDestinationUrl,
  integratedDestinationLabel,
  integratedDestinationNote,
}) => {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 rounded-full bg-[#10A37F]/10 border border-[#10A37F]/30 px-3 py-0.5 text-xs font-semibold text-[#10A37F]">
            <Clock className="h-3.5 w-3.5" />
            <span>Scheduled for {phase}</span>
          </span>
          <span className="text-xs text-[#A1A1AA]">Module Lead: {owner}</span>
        </div>

        <div>
          <h2 className="text-xl font-bold text-[#ECECEC]">{title}</h2>
          <p className="mt-1.5 text-xs text-[#A1A1AA] leading-relaxed">{summary}</p>
        </div>

        {integratedDestinationUrl && (
          <div className="rounded-lg border border-[#10A37F]/40 bg-[#10A37F]/10 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#10A37F]">
                <Sparkles className="h-4 w-4" />
                <span>Functionality Available in Integrated Workbench</span>
              </div>
              <p className="text-xs text-[#ECECEC]">
                {integratedDestinationNote || 'This functionality is available directly in the primary workflow.'}
              </p>
            </div>
            <Link
              to={integratedDestinationUrl}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#10A37F] hover:bg-[#0D8F70] px-3.5 py-1.5 text-xs font-semibold text-white transition shrink-0"
            >
              <span>Open {integratedDestinationLabel || 'Workbench'}</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}

        <div className="rounded-lg border border-[#424242] bg-[#212121] p-4 space-y-2.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#ECECEC]">
            <ShieldCheck className="h-4 w-4 text-[#10A37F]" />
            <span>Planned Engineering Deliverables ({phase})</span>
          </div>
          <ul className="space-y-1.5 text-xs text-[#A1A1AA] list-disc list-inside">
            {deliverables.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="pt-2">
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-lg border border-[#424242] bg-[#212121] px-3.5 py-1.5 text-xs font-medium text-[#A1A1AA] hover:bg-[#424242] hover:text-[#ECECEC] transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Return to Phase 1 System Telemetry</span>
          </Link>
        </div>
      </div>
    </div>
  );
};
