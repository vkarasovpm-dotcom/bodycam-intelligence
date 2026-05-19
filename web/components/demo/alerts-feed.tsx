"use client";

import { motion, AnimatePresence } from 'framer-motion';
import { useSessionStore } from '../../lib/stores/session-store';
import { formatRuleSubject, formatSeverity, severityBgClass, subjectBorderClass } from '../../lib/format/rule-subject';
import { formatTime } from '../../lib/format/time';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import { HelpCircle, Zap } from 'lucide-react';

export function AlertsFeed() {
  const currentT = useSessionStore(state => state.currentT);
  const session = useSessionStore(state => state.session);

  const rapidAlerts = session?.rapid_alerts ?? [];
  const visibleAlerts = rapidAlerts
    .filter(alert => alert.t_utterance <= currentT)
    .sort((a, b) => b.t_utterance - a.t_utterance);

  return (
    <div className="flex flex-col rounded-xl border border-white/[0.06] bg-white/[0.03] hover:border-emerald-500/30 hover:bg-white/[0.05] p-5 max-h-[400px]">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800/50 pb-3 mb-4 bg-transparent">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-semibold text-slate-200">Rapid Alerts</h2>
          <span className="text-xs text-slate-500">({visibleAlerts.length})</span>
        </div>
        <Tooltip>
          <TooltipTrigger>
            <HelpCircle className="h-4 w-4 text-slate-500 hover:text-slate-400" />
          </TooltipTrigger>
          <TooltipContent className="max-w-[280px] bg-slate-800 text-slate-200 border-slate-700">
            <p>Rapid prosecution by Featherless (google/gemma-4-26B-A4B-it). Routed via custom triage, retrieved via FAISS case-law search. Sub-3s latency per utterance.</p>
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 space-y-3">
        {visibleAlerts.length === 0 ? (
          <div className="flex items-center gap-3 rounded-lg border border-white/[0.06] bg-white/[0.03] p-4 text-sm text-slate-400">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
            <p>Layer 1 monitoring active. First alert appears when prosecution agent fires.</p>
          </div>
        ) : (
          <AnimatePresence>
            {visibleAlerts.map(alert => (
              <motion.div
                key={`${alert.rule_id}-${alert.utt_index}`}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3 }}
                className={`flex flex-col rounded-lg border border-white/[0.06] bg-white/[0.03] p-3 border-l-4 ${subjectBorderClass(alert.subject)}`}
              >
                <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${severityBgClass(alert.severity)}`}>
                    {formatSeverity(alert.severity)}
                  </span>
                  <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                    {formatRuleSubject(alert.subject)}
                  </span>
                  <span className="text-slate-600">&middot;</span>
                  <span className="text-xs text-slate-500 font-mono">
                    at {formatTime(alert.t_utterance)}
                  </span>
                </div>
                
                <h3 className="text-sm font-medium text-slate-200">
                  {alert.rule_title}
                </h3>
                
                <p className="mt-1 text-xs text-slate-400 line-clamp-2">
                  {alert.one_liner}
                </p>
                
                <div className="mt-3 text-right">
                  <span className="text-[10px] text-slate-600 font-mono">
                    via Featherless &middot; {alert.model_used}
                  </span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
