import { SeverityLabel } from '../types/session';

export function formatRuleSubject(subject: string): string {
  switch (subject) {
    case 'officer':
      return 'Officer';
    case 'officer_partner':
      return 'Partner officer';
    case 'civilian':
      return 'Civilian';
    case 'subject':
      return 'Subject';
    case 'both':
      return 'Both parties';
    default:
      if (!subject) return '';
      // Capitalize first letter, replace underscores with spaces
      const spaced = subject.replace(/_/g, ' ');
      return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }
}

export function formatSeverity(sev: SeverityLabel): string {
  if (!sev) return '';
  return sev.charAt(0).toUpperCase() + sev.slice(1);
}

export function formatVerdict(v: string): string {
  if (!v) return '';
  return v.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

export function severityColor(sev: SeverityLabel): string {
  switch (sev) {
    case 'none':
      return 'text-slate-500';
    case 'low':
      return 'text-yellow-500';
    case 'medium':
      return 'text-orange-500';
    case 'high':
      return 'text-red-500';
    case 'critical':
      return 'text-red-700';
    default:
      return 'text-slate-500';
  }
}

export function severityBgClass(sev: SeverityLabel): string {
  switch (sev) {
    case 'none': return 'bg-slate-500/15 text-slate-300 border border-slate-500/30';
    case 'low': return 'bg-yellow-500/15 text-yellow-300 border border-yellow-500/30';
    case 'medium': return 'bg-orange-500/15 text-orange-300 border border-orange-500/30';
    case 'high': return 'bg-red-500/15 text-red-300 border border-red-500/30';
    case 'critical': return 'bg-red-700/15 text-red-400 border border-red-700/30';
    default: return 'bg-slate-500/15 text-slate-300 border border-slate-500/30';
  }
}

export function subjectBorderClass(subject: string): string {
  if (!subject) return 'border-l-slate-500';
  const s = subject.toLowerCase();
  if (s.includes('officer')) return 'border-l-red-500';
  if (s.includes('citizen') || s.includes('civilian')) return 'border-l-amber-500';
  return 'border-l-sky-500';
}
