"use client";

import { useState } from 'react';
import { useSessionStore } from '../../lib/stores/session-store';
import { DeepViolation } from '../../lib/types/session';
import { severityBgClass, formatSeverity } from '../../lib/format/rule-subject';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import { Shield, HelpCircle, ChevronRight, ChevronDown } from 'lucide-react';

function ViolationCard({ violation }: { violation: DeepViolation }) {
  const [expanded, setExpanded] = useState(false);
  const session = useSessionStore(state => state.session);
  
  const rebuttal = session?.rebuttals.find(r => r.challenges_rule_id === violation.rule_id);

  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.03] p-3 mb-3">
      <div 
        className="flex items-start justify-between cursor-pointer group"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 flex-wrap flex-1 pr-2">
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider shrink-0 ${severityBgClass(violation.severity)}`}>
            {formatSeverity(violation.severity)}
          </span>
          <h3 className="text-sm font-medium text-slate-200">
            {violation.title}
          </h3>
        </div>
        <div className="shrink-0 text-slate-500 group-hover:text-slate-300 transition-colors mt-0.5">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>
      </div>

      <div className="mt-2">
        <p className={`text-xs text-slate-400 ${!expanded && 'line-clamp-2'}`}>
          {violation.rationale}
        </p>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3">
          <div className="text-xs text-slate-500 font-mono">
            Cited utterances: {violation.cited_utterances.join(', ')}
          </div>
          
          {rebuttal && (
            <div className="border-t border-slate-800 pt-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-medium text-amber-400">⚖ Defense argues:</span>
                {rebuttal.proposed_severity_adjustment && (
                  <span className="text-[10px] font-mono text-slate-500 bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5">
                    Severity: {rebuttal.proposed_severity_adjustment}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-300">
                {rebuttal.counter_argument}
              </p>
            </div>
          )}
        </div>
      )}

      <div className="mt-2 text-right">
        <span className="text-[10px] font-mono text-slate-600">
          confidence {Math.round(violation.confidence * 100)}%
        </span>
      </div>
    </div>
  );
}

export function DeepScanFeed() {
  const visibleEvents = useSessionStore(state => state.visibleEvents);
  const session = useSessionStore(state => state.session);

  const hasDeepScan = visibleEvents.some(e => e.kind === 'deep_scan_completed');
  const utteranceCount = visibleEvents.filter(e => e.kind === 'utterance').length;

  const violations = session?.deep_violations ?? [];
  const rebuttals = session?.rebuttals ?? [];

  return (
    <div className="flex flex-col rounded-xl border border-white/[0.06] bg-white/[0.03] hover:border-emerald-500/30 hover:bg-white/[0.05] p-5 h-full transition-colors">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800/50 pb-3 mb-4 bg-transparent">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-200">Deep Scans</h2>
          {hasDeepScan && (
            <span className="text-xs text-slate-500">
              ({violations.length} findings &middot; {rebuttals.length} rebuttals)
            </span>
          )}
        </div>
        <Tooltip>
          <TooltipTrigger>
            <HelpCircle className="h-4 w-4 text-slate-500 hover:text-slate-400" />
          </TooltipTrigger>
          <TooltipContent className="max-w-[280px] bg-slate-800 text-slate-200 border-slate-700">
            <p>Deep adversarial reasoning by Featherless (openai/gpt-oss-120b for Prosecution, google/gemma-4-31B-it for Defense). Triggered every 10 utterances or 60s. Async-first — never blocks Layer 1.</p>
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="flex-1 overflow-y-auto pr-2">
        {!hasDeepScan ? (
          <div className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.03] p-4 text-sm text-slate-400">
            <p>First deep scan triggers at 10 utterances or 60 seconds. Current: <span className="font-mono text-emerald-500">{utteranceCount}</span> utterances elapsed.</p>
          </div>
        ) : (
          <div>
            {violations.map(violation => (
              <ViolationCard key={violation.rule_id} violation={violation} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
