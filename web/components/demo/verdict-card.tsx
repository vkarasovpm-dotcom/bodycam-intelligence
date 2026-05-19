"use client";

import { useRef, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useSessionStore } from '../../lib/stores/session-store';
import { formatSeverity, severityColor, severityBgClass } from '../../lib/format/rule-subject';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import { HelpCircle } from 'lucide-react';

export function VerdictCard() {
  const currentVerdict = useSessionStore(state => state.currentVerdict);
  const prevHeadlineRef = useRef<string | null>(null);
  const [scaleKey, setScaleKey] = useState(0);

  useEffect(() => {
    if (currentVerdict && currentVerdict.headline !== prevHeadlineRef.current) {
      setScaleKey(prev => prev + 1);
      prevHeadlineRef.current = currentVerdict.headline;
    }
  }, [currentVerdict]);

  if (!currentVerdict) {
    return (
      <div className="relative flex flex-col rounded-2xl bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] p-6 min-h-[250px] transition-colors">
        <div className="flex justify-between items-start mb-6">
          <div className="h-6 w-20 rounded-full bg-slate-800/30 animate-pulse"></div>
          <HelpCircle className="h-5 w-5 text-slate-700" />
        </div>
        <div className="h-8 w-3/4 bg-slate-800/30 rounded mb-4 animate-pulse"></div>
        <div className="h-4 w-full bg-slate-800/20 rounded mb-2 animate-pulse"></div>
        <div className="h-4 w-5/6 bg-slate-800/20 rounded mb-6 animate-pulse"></div>
        
        <div className="mt-auto pt-4 flex justify-between border-t border-slate-800/30">
          <div className="h-3 w-1/3 bg-slate-800/20 rounded animate-pulse"></div>
        </div>
        <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
          <span className="text-slate-500 font-medium">Awaiting first verdict...</span>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      key={scaleKey}
      animate={{ scale: [1.02, 1] }}
      transition={{ duration: 0.4 }}
      className="flex flex-col rounded-2xl bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] p-6 shadow-xl transition-colors"
    >
      <div className="flex justify-between items-start">
        <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium uppercase tracking-wider ${severityBgClass(currentVerdict.overall_severity)}`}>
          {formatSeverity(currentVerdict.overall_severity)}
        </span>
        <Tooltip>
          <TooltipTrigger>
            <HelpCircle className="h-5 w-5 text-slate-500 hover:text-slate-400 transition-colors" />
          </TooltipTrigger>
          <TooltipContent className="max-w-[250px] bg-slate-800 text-slate-200 border-slate-700">
            <p>Final adjudication by Google Gemini 3.1 Pro.<br/>Weighs prosecution vs defense per rule, issues auditable rulings.<br/>Verdict evolves as new evidence arrives.</p>
          </TooltipContent>
        </Tooltip>
      </div>

      <h3 className="mt-3 text-2xl font-semibold text-white leading-tight">
        {currentVerdict.headline}
      </h3>
      
      <p className="mt-2 text-sm text-slate-400 line-clamp-3">
        {currentVerdict.summary}
      </p>

      {currentVerdict.rulings && currentVerdict.rulings.length > 0 && (
        <div className="mt-5 flex flex-col gap-3">
          {currentVerdict.rulings.map(ruling => (
            <div key={ruling.rule_id} className="rounded-lg border border-white/[0.06] bg-white/[0.03] p-3">
              <div className="flex items-start justify-between mb-1">
                <span className="text-sm font-medium text-slate-200">{ruling.title}</span>
                <span className={`text-xs font-semibold ${severityColor(ruling.final_severity)}`}>
                  {ruling.verdict.replace(/_/g, ' ').toUpperCase()}
                </span>
              </div>
              <p className="text-xs text-slate-400 line-clamp-2">
                {ruling.reasoning}
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="mt-6 flex items-center text-xs text-slate-500 font-mono">
        {currentVerdict.n_violations} violations &middot; {currentVerdict.n_rebuttals} rebuttals &middot; confidence {Math.round(currentVerdict.rulings.reduce((acc, r) => acc + r.confidence, 0) / Math.max(1, currentVerdict.rulings.length) * 100)}%
      </div>
    </motion.div>
  );
}
