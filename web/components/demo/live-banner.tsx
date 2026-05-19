"use client";

import { motion, AnimatePresence } from 'framer-motion';
import { useSessionStore } from '../../lib/stores/session-store';
import { formatRuleSubject, formatSeverity, severityBgClass } from '../../lib/format/rule-subject';

function getSubjectBorder(subject: string) {
  const s = subject.toLowerCase();
  if (s.includes('officer')) return 'border-l-red-500';
  if (s.includes('citizen') || s.includes('civilian')) return 'border-l-amber-500';
  return 'border-l-sky-500';
}

export function LiveBanner() {
  const activeRapidAlerts = useSessionStore(state => state.activeRapidAlerts);
  const activeAlert = activeRapidAlerts.length > 0 ? activeRapidAlerts[activeRapidAlerts.length - 1] : null;

  return (
    <AnimatePresence mode="wait">
      {activeAlert && (
        <motion.div
          key={`${activeAlert.utt_index}-${activeAlert.t_utterance}`}
          initial={{ y: -20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -10, opacity: 0 }}
          transition={{ duration: 0.25 }}
          className={`mb-6 rounded-xl bg-white/[0.03] border border-white/[0.06] border-l-4 p-4 shadow-lg ${getSubjectBorder(activeAlert.subject)}`}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${severityBgClass(activeAlert.severity)}`}>
              {formatSeverity(activeAlert.severity)}
            </span>
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              {formatRuleSubject(activeAlert.subject)}
            </span>
            <span className="text-slate-600 mx-1">&middot;</span>
            <span className="text-sm font-semibold text-white leading-tight">
              {activeAlert.rule_title}
            </span>
          </div>
          
          <p className="text-sm text-slate-300 mt-1">
            {activeAlert.one_liner}
          </p>
          
          <p className="text-xs text-slate-500 italic mt-2">
            Quote: "{activeAlert.triggering_quote}"
          </p>
          
          <div className="mt-3 text-right">
            <span className="text-[10px] text-slate-600 font-mono truncate">
              via Featherless &middot; {activeAlert.model_used}
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
