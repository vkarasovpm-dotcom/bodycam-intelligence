export type SeverityLabel = 'none' | 'low' | 'medium' | 'high' | 'critical';

export interface KeyMoment {
  t_seconds: number;
  description: string;
  significance: string;
}

export interface VisualContext {
  video_path: string;
  duration_sec: number;
  subjects_visible: number;
  officers_visible: number;
  environment: string;
  restraints_visible: boolean;
  restraints_timing: number | null;
  weapons_drawn_by_officer: boolean;
  weapon_type: string | null;
  subject_armed: boolean;
  force_observed: boolean;
  force_description: string;
  injuries_visible: boolean;
  subject_compliance: string;
  officer_misconduct_indicators: string[];
  citizen_violation_indicators: string[];
  key_moments: KeyMoment[];
  summary: string;
  model_used: string;
  latency_ms: number;
}

export interface RetrievalScore {
  rule_id: string;
  score: number;
}

export interface RapidAlert {
  rule_id: string;
  rule_title: string;
  rule_source: string;
  severity: SeverityLabel;
  subject: string;
  confidence: number;
  one_liner: string;
  triggering_quote: string;
  classification: string;
  region: string;
  retrieval_scores: RetrievalScore[];
  model_used: string;
  latency_ms: number;
  utt_index: number;
  t_utterance: number;
  atom_ms: number;
}

export interface Ruling {
  rule_id: string;
  title: string;
  verdict: string;
  final_severity: SeverityLabel;
  reasoning: string;
  key_utterances: number[];
  prosecution_weight: number;
  defense_weight: number;
  confidence: number;
}

export interface FinalVerdict {
  at_t: number;
  reason: string;
  wall_ms: number;
  overall_verdict: string;
  overall_severity: SeverityLabel;
  headline: string;
  summary: string;
  rulings: Ruling[];
  n_violations: number;
  n_rebuttals: number;
}

export interface DeepViolation {
  rule_id: string;
  title: string;
  source: string;
  severity: SeverityLabel;
  cited_utterances: number[];
  rationale: string;
  confidence: number;
}

export interface Rebuttal {
  challenges_rule_id: string;
  stance: string;
  counter_argument: string;
  counter_utterances: number[];
  proposed_severity_adjustment: string | null;
  confidence: number;
}

export type VerdictTimelineSnapshot = FinalVerdict;

export interface UtteranceEvent {
  t: number;
  kind: 'utterance';
  text: string;
  speaker: string;
  t_start: number;
  t_end: number;
  utt_index: number;
}

export interface RouterSkipEvent {
  t: number;
  kind: 'router_skip';
  utt_index: number;
  classification: string;
  reason?: string;
  atom_ms?: number;
  confidence?: number;
}

export interface SessionFinalizingEvent {
  t: number;
  kind: 'session_finalizing';
}

export interface DeepScanStartedEvent {
  t: number;
  kind: 'deep_scan_started';
  triggers: string[];
  utterances: number;
}

export interface VisualContextReadyEvent {
  t: number;
  kind: 'visual_context_ready';
  force_observed: boolean;
  restraints_visible: boolean;
  restraints_timing: number | null;
  weapons_drawn: boolean;
  subject_compliance: string;
  key_moments: number;
  summary: string;
  model_used: string;
  latency_ms: number;
}

export interface DeepScanCompletedEvent {
  t: number;
  kind: 'deep_scan_completed';
  wall_ms: number;
  violations: number;
  rebuttals: number;
  prosecution_verdict: string;
  overall_severity: SeverityLabel;
}

export interface VerdictUpdateEvent {
  t: number;
  kind: 'verdict_update';
  at_t: number;
  reason: string;
  wall_ms: number;
  overall_verdict: string;
  overall_severity: SeverityLabel;
  headline: string;
  summary: string;
  rulings: Ruling[];
  n_violations: number;
  n_rebuttals: number;
}

export interface DeepScanSkippedEvent {
  t: number;
  kind: 'deep_scan_skipped';
  reason: string;
  triggers: string[];
}

export interface RapidAlertEvent extends RapidAlert {
  t: number;
  kind: 'rapid_alert';
}

export type SessionEvent =
  | UtteranceEvent
  | RouterSkipEvent
  | SessionFinalizingEvent
  | DeepScanStartedEvent
  | VisualContextReadyEvent
  | DeepScanCompletedEvent
  | VerdictUpdateEvent
  | DeepScanSkippedEvent
  | RapidAlertEvent;

export interface SessionMeta {
  session_id: string;
  region: string;
  vertical: string;
  started_at: number;
  transcript_path: string;
  total_utterances: number;
}

export interface SessionStats {
  total_utterances: number;
  rapid_alerts: number;
  deep_violations: number;
  rebuttals: number;
  verdict_snapshots: number;
  router_skips: number;
}

export interface Session {
  session_id: string;
  region: string;
  vertical: string;
  meta: SessionMeta;
  rapid_alerts: RapidAlert[];
  visual_context: VisualContext;
  deep_violations: DeepViolation[];
  rebuttals: Rebuttal[];
  verdict_timeline: VerdictTimelineSnapshot[];
  final_verdict: FinalVerdict;
  events: SessionEvent[];
  stats: SessionStats;
}
