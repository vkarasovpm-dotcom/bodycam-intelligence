"""SENTINEL Rapid Prosecution — single-utterance alert generator for live mode.

Differs from ProsecutionAgent (full):
- Input: ONE utterance + ≤5 prior context + retrieval top-3 rules
- Output: ONE alert (or none) — not a multi-violation report
- Token budget: ≤200 output tokens, target <1.5s wall time
- Model: gpt-oss-20b (smaller, faster) with gemma-26B fallback
"""
from __future__ import annotations
import json, os, re, sys, time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from agents.base import Trace, featherless_client, MODELS
from agents.retrieval_agent import RetrievalAgent, RuleHit


@dataclass
class RapidAlert:
    rule_id: str
    rule_title: str
    rule_source: str
    severity: str                # none | low | medium | high | critical
    subject: str                 # officer | citizen
    confidence: float            # 0..1
    one_liner: str               # ≤120 chars, what was violated
    triggering_quote: str        # the utterance that triggered
    classification: str          # from router
    region: str
    retrieval_scores: list[dict] = field(default_factory=list)  # [{rule_id, score}, ...]
    model_used: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


RAPID_PROSECUTION_SYSTEM = """You are a real-time prosecutor for police bodycam analysis. You receive ONE utterance, prior context, a router classification, and up to 3 candidate legal rules from a retrieval system.

Your job: decide if this specific utterance, in this context, breaches one of the candidate rules. If yes, produce a single concise alert. If no, return null.

Rules:
- Be FAST and DECISIVE — this is real-time triage, not a full brief.
- Cite ONLY one of the candidate rule IDs provided. Do NOT invent rule IDs.
- one_liner is ≤120 chars, written as a courtroom statement of the alleged violation.
- confidence reflects how clearly THIS utterance breaches THIS rule in context.
- If multiple candidates apply, pick the one with highest severity that actually fits.
- If the utterance is innocuous, return {"alert": null}.

DECISIVENESS HEURISTIC (real-time triage, not appellate review):
- TRUST the router classification and the top retrieval hit. If router says
  officer_violation OR escalation, AND top hit score >= 0.55, AND top hit
  subject = officer → YOU MUST EMIT AN ALERT. Do not return null.
- The router and retrieval have already filtered out innocuous speech. Your
  default leaning when reaching this stage is TO EMIT an alert.

MANDATORY ALERT TRIGGERS (emit alert without further analysis):
1. Utterance contains "search" / "let me search" / "I'll search" / "pat down"
   AND prior context does NOT contain "consent" / "permission" / "warrant" /
   "probable cause" → US-4A-SEARCH or US-4A-FRISK violation. ALWAYS EMIT.
2. Utterance contains "you're under arrest" / "in custody" / "going to jail"
   AND prior context does NOT contain "right to remain silent" / Miranda
   warning → US-5A-MIRANDA violation. ALWAYS EMIT.
3. Utterance contains "stop recording" / "stop filming" / "put the camera down"
   directed at a citizen → US-1A-RECORD violation. ALWAYS EMIT.
4. Utterance contains "stop the car" / "pull over" / "show me your ID"
   AND prior context does NOT establish reasonable suspicion → US-4A-STOP
   violation. ALWAYS EMIT.
5. Officer threatens jail/arrest without stating cause → US-4A-ARREST-PC.
   ALWAYS EMIT.

INFERENCE FROM ABSENCE IS VALID: do NOT require the officer to say
"I am violating your rights." That never happens. The violation IS the
absence of the required procedural step in prior context.

Return {"alert": null} ONLY if:
- The utterance is genuinely innocuous (greeting, mundane), OR
- Prior context EXPLICITLY shows the procedural requirement was met
  (e.g. Miranda was read, consent was given, RAS was stated).
  
Respond with STRICT JSON only:
{
  "alert": {
    "rule_id": "<one of provided IDs>",
    "severity": "<low|medium|high|critical>",
    "confidence": <0.0-1.0>,
    "one_liner": "<≤120 chars>"
  }
}
OR
{"alert": null}
"""


def _format_candidates(hits: list[RuleHit]) -> str:
    lines = []
    for h in hits:
        lines.append(
            f"- {h.rule_id} | severity={h.severity} | subject={h.subject}\n"
            f"  title: {h.title}\n"
            f"  source: {h.source[:120]}\n"
            f"  summary: {h.summary[:240]}"
        )
    return "\n".join(lines)


def _format_context(context: list[str]) -> str:
    if not context:
        return "(no prior context)"
    return "\n".join(f"- {c}" for c in context[-5:])


class RapidProsecutionAgent:
    def __init__(self, region: str = "us", vertical: str = "police",
                 trace: Optional[Trace] = None,
                 retrieval: Optional[RetrievalAgent] = None):
        self.region = region.lower()
        self.vertical = vertical.lower()
        self.trace = trace or Trace()
        self.retrieval = retrieval or RetrievalAgent(trace=self.trace)
        # Primary: gemma-26B — stable JSON output, ~4-5s on Featherless.
        # Fallback: gpt-oss-20b — used only if primary returns empty.
        self.primary_model = MODELS.get("prosecution_alt", MODELS["prosecution"])
        self.fallback_model = MODELS.get("rapid", MODELS["defense_alt"])
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = featherless_client()
        return self._client

    def _retrieve(self, query: str, classification: str, top_k: int = 3) -> list[RuleHit]:
        # Filter retrieval by subject when classification is clearly officer/citizen
        subject_filter = None
        if classification == "officer_violation":
            subject_filter = "officer"
        elif classification == "citizen_violation":
            subject_filter = "citizen"
        return self.retrieval.search(query, region=self.region,
                                     top_k=top_k, subject_filter=subject_filter)

    def _call_model(self, model: str, user_prompt: str) -> str:
        """Single Featherless call. Returns raw assistant content (may be empty)."""
        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": RAPID_PROSECUTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=220,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        return content.strip()

    def _parse_alert(self, raw: str) -> Optional[dict]:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        try:
            obj = json.loads(clean)
        except Exception:
            # try to find {"alert": ...} substring
            m = re.search(r'\{.*"alert".*\}', clean, re.S)
            if not m:
                return None
            try:
                obj = json.loads(m.group(0))
            except Exception:
                return None
        alert = obj.get("alert")
        if alert is None or not isinstance(alert, dict):
            return None
        return alert

    def _build_critical_event_alert(self, utterance: str) -> Optional[RapidAlert]:
        """Critical events get templated alerts with ~5ms latency.
        Bypasses retrieval + LLM. Five categories matched by keyword,
        plus a generic fallback so signal is never dropped."""
        t0 = time.perf_counter()
        text_low = utterance.lower()

        def _mk(rule_id: str, title: str, source: str, severity: str,
                subject: str, confidence: float, one_liner: str) -> RapidAlert:
            return RapidAlert(
                rule_id=rule_id,
                rule_title=title,
                rule_source=source,
                severity=severity,
                subject=subject,
                confidence=confidence,
                one_liner=one_liner,
                triggering_quote=utterance,
                classification="critical_event",
                region=self.region,
                model_used="keyword_fastpath",
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            )

        # Category 1: Armed subject — officer commanding weapon down
        armed_keys = [
            "drop the knife", "drop the gun", "drop the weapon",
            "drop it now", "put the knife", "put the gun",
            "he's got a gun", "he's got a knife", "she's got a gun",
            "she's got a knife", "got a weapon", "show me the knife",
            "show me the gun",
            "lascia il coltello", "lascia la pistola",
            "lass das messer", "lass die waffe",
            "lâche le couteau", "lâche l'arme",
            "suelta el cuchillo", "suelta el arma",
        ]
        if any(k in text_low for k in armed_keys):
            return _mk(
                "CRIT-ARMED-SUBJECT",
                "Armed Subject — Use of Force Imminent",
                "Operational flag — Graham v. Connor reasonableness analysis applies",
                "critical", "citizen", 0.95,
                "Subject is armed. Officer issuing weapon-down commands. Force may be imminent.",
            )

        # Category 2: Less-lethal force deployment (taser)
        taser_keys = [
            "taser, taser", "taser taser taser", "deploying taser",
            "tase him", "tase her",
            "taser, taser, taser",
            "elektroschocker", "pistolet à impulsion", "pistola eléctrica",
        ]
        if any(k in text_low for k in taser_keys):
            return _mk(
                "CRIT-FORCE-TASER",
                "Less-Lethal Force Deployed — Taser",
                "Force continuum — taser deployment requires active resistance or threat",
                "high", "officer", 0.95,
                "Officer deployed taser. Justification must be documented; medical check required.",
            )

        # Category 3: Officer in distress / active gunfire on scene
        distress_keys = [
            "officer down", "shots fired", "10-33", "help me",
            "code three", "code 3", "officer needs assistance",
            "agente ferito", "spari", "aiuto",
            "polizist verletzt", "schüsse", "hilfe",
            "agent à terre", "coups de feu", "à l'aide",
            "agente herido", "disparos", "ayuda",
        ]
        if any(k in text_low for k in distress_keys):
            return _mk(
                "CRIT-OFFICER-DISTRESS",
                "Officer in Distress — Emergency Response Required",
                "Operational flag — backup dispatch and command notification mandatory",
                "critical", "officer", 0.97,
                "Officer signals distress or active gunfire. Immediate backup required.",
            )

        # Category 4: Lethal force discharged
        lethal_keys = [
            "shots fired by police", "i'm hit", "he's hit", "she's hit",
            "stop shooting", "cease fire", "i shot him", "i shot her",
            "ho sparato", "habe geschossen", "j'ai tiré", "he disparado",
        ]
        if any(k in text_low for k in lethal_keys):
            return _mk(
                "CRIT-FORCE-LETHAL",
                "Lethal Force Discharged",
                "Tennessee v. Garner / Graham v. Connor — deadly force review mandatory",
                "critical", "officer", 0.97,
                "Firearm discharged. Mandatory IA investigation, scene preservation, medical aid.",
            )

        # Category 5: Final verbal warning before force escalation
        warning_keys = [
            "last warning", "final warning", "i will shoot", "i will tase",
            "stop or i'll", "don't make me", "this is your last chance",
            "ultimo avvertimento", "ultima possibilità",
            "letzte warnung", "letzte chance",
            "dernier avertissement", "dernière chance",
            "última advertencia", "última oportunidad",
        ]
        if any(k in text_low for k in warning_keys):
            return _mk(
                "CRIT-FINAL-WARNING",
                "Final Warning Issued — Force Imminent",
                "Force continuum — verbal warning preceding escalation",
                "high", "officer", 0.92,
                "Officer issued final verbal warning. Next escalation step likely.",
            )

        # Generic fallback — router flagged critical_event but no keyword bank
        # matched. Emit a low-confidence generic alert rather than drop signal.
        return _mk(
            "CRIT-GENERIC",
            "Critical Event Detected",
            "Router classified utterance as critical_event; specific category not matched",
            "high", "officer", 0.55,
            "Critical-event signal detected. Manual review recommended.",
        )

    def run(self, utterance: str, context: list[str],
            classification: str, query_rewrite: str = "") -> Optional[RapidAlert]:
        t_start = time.perf_counter()

        if classification == "none":
            self.trace.emit("rapid_prosecution", "skip", data={"reason": "router_none"})
            return None

        # Fast path — critical_event bypasses retrieval and LLM
        if classification == "critical_event":
            alert = self._build_critical_event_alert(utterance)
            if alert:
                self.trace.emit("rapid_prosecution", "critical_event_emitted", data={
                    "rule_id": alert.rule_id, "severity": alert.severity,
                    "subject": alert.subject,
                })
            return alert

        # 1. Retrieval — use query_rewrite if available, else raw utterance
        query = query_rewrite or utterance
        hits = self._retrieve(query, classification, top_k=3)
        self.trace.emit("rapid_prosecution", "retrieved", data={
            "query": query[:120],
            "top_hits": [{"rule_id": h.rule_id, "score": round(h.score, 3)} for h in hits],
        })
        if not hits:
            return None

        # Upgrade: if classification=escalation but top retrieval hit is a strong
        # officer-subject rule, re-classify as officer_violation for the LLM stage.
        # This catches cases like "you are under arrest" (no Miranda) which the
        # router conservatively labels as escalation.
        if classification == "escalation":
            top = hits[0]
            top_subject = getattr(top, "subject", None)
            if top.score >= 0.50 and top_subject == "officer":
                self.trace.emit("rapid_prosecution", "upgrade", data={
                    "from": "escalation", "to": "officer_violation",
                    "reason": f"top hit {top.rule_id} score={top.score:.2f} subject=officer",
                })
                classification = "officer_violation"

        # 2. Build prompt
        user_prompt = (
            f"REGION: {self.region}\n"
            f"ROUTER CLASSIFICATION: {classification}\n\n"
            f"PRIOR CONTEXT:\n{_format_context(context)}\n\n"
            f"CURRENT UTTERANCE:\n\"{utterance}\"\n\n"
            f"CANDIDATE RULES (top-3 from retrieval):\n{_format_candidates(hits)}\n\n"
            f"Decide if the current utterance breaches one of these rules. STRICT JSON only."
        )

        # 3. Call primary; retry on empty/short response or exception, then fallback.
        model_used = self.primary_model
        raw = ""
        try:
            raw = self._call_model(self.primary_model, user_prompt)
        except Exception as e:
            self.trace.emit("rapid_prosecution", "primary_failed", data={
                "model": self.primary_model, "error": str(e)[:160]})

        # Retry with fallback model if primary returned empty or absurdly short content
        if not raw or len(raw.strip()) < 10:
            self.trace.emit("rapid_prosecution", "primary_empty_retry_fallback", data={
                "primary": self.primary_model, "primary_chars": len(raw),
                "fallback": self.fallback_model,
            })
            try:
                raw = self._call_model(self.fallback_model, user_prompt)
                model_used = self.fallback_model
            except Exception as e2:
                self.trace.emit("rapid_prosecution", "both_failed", data={"error": str(e2)[:160]})
                return None

        alert_dict = self._parse_alert(raw)
        if not alert_dict:
            self.trace.emit("rapid_prosecution", "no_alert", data={"raw_chars": len(raw)})
            return None

        # 4. Resolve rule_id back to full RuleHit (for title/source/subject)
        rule_id = alert_dict.get("rule_id", "")
        match = next((h for h in hits if h.rule_id == rule_id), None)
        if not match:
            # LLM cited an ID not in candidates → reject (anti-hallucination)
            self.trace.emit("rapid_prosecution", "hallucinated_rule_id", data={
                "cited": rule_id, "candidates": [h.rule_id for h in hits]})
            return None

        latency_ms = (time.perf_counter() - t_start) * 1000
        alert = RapidAlert(
            rule_id=rule_id,
            rule_title=match.title,
            rule_source=match.source,
            severity=str(alert_dict.get("severity", match.severity)).lower(),
            subject=match.subject,
            confidence=float(alert_dict.get("confidence", 0.5)),
            one_liner=str(alert_dict.get("one_liner", ""))[:180],
            triggering_quote=utterance,
            classification=classification,
            region=self.region,
            retrieval_scores=[{"rule_id": h.rule_id, "score": round(h.score, 3)} for h in hits],
            model_used=model_used,
            latency_ms=round(latency_ms, 1),
        )
        self.trace.emit("rapid_prosecution", "alert_emitted", data={
            "rule_id": rule_id, "severity": alert.severity,
            "confidence": alert.confidence, "latency_ms": alert.latency_ms,
            "model": model_used,
        })
        return alert


# ---------------------------------------------------------------------------
# CLI — full atom test: router → rapid prosecution → alert
# ---------------------------------------------------------------------------

def _cli():
    import argparse
    p = argparse.ArgumentParser(description="SENTINEL Rapid Prosecution — single-utterance alert")
    p.add_argument("--text", required=True)
    p.add_argument("--context", default="")
    p.add_argument("--region", default="us")
    p.add_argument("--skip-router", action="store_true",
                   help="Skip router (assume officer_violation classification)")
    p.add_argument("--classification", default=None,
                   help="Override router classification (e.g. critical_event, officer_violation)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    from agents.router_agent import RouterAgent
    context = [c.strip() for c in args.context.split("|") if c.strip()] if args.context else []

    trace = Trace()
    t0 = time.perf_counter()

    if args.classification:
        cls = args.classification
        rewrite = args.text
        router_ms = 0.0
    elif args.skip_router:
        cls = "officer_violation"
        rewrite = args.text
        router_ms = 0.0
    else:
        router = RouterAgent(region=args.region, trace=trace)
        rc = router.classify(args.text, context)
        cls = rc.classification
        rewrite = rc.query_rewrite or args.text
        router_ms = rc.latency_ms

    pros = RapidProsecutionAgent(region=args.region, trace=trace)
    alert = pros.run(args.text, context, cls, query_rewrite=rewrite)
    total_ms = (time.perf_counter() - t0) * 1000

    if args.json:
        out = {
            "classification": cls,
            "router_ms": round(router_ms, 1),
            "total_ms": round(total_ms, 1),
            "alert": alert.to_dict() if alert else None,
            "trace": trace.to_list(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    print("=" * 70)
    print(f"ATOM TEST  region={args.region}")
    print(f"  Utterance: {args.text}")
    if context:
        print(f"  Context  : {len(context)} prior")
    print(f"  Router   : {cls}   ({router_ms:.0f}ms)")
    print(f"  Rewrite  : \"{rewrite}\"")
    print(f"  Total    : {total_ms:.0f}ms")
    print("=" * 70)
    if alert is None:
        print("  → No alert emitted.")
    else:
        sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡",
                    "low": "🟢", "none": "⚪"}.get(alert.severity, "?")
        subj_icon = {"officer": "👮", "citizen": "👤"}.get(alert.subject, "?")
        print(f"\n  {sev_icon} ALERT  {subj_icon} {alert.subject.upper():8s}  "
              f"sev={alert.severity:8s}  conf={alert.confidence:.2f}")
        print(f"  Rule  : {alert.rule_id} — {alert.rule_title}")
        print(f"  Source: {alert.rule_source[:90]}")
        print(f"  One-liner: {alert.one_liner}")
        print(f"  Model : {alert.model_used}  Latency: {alert.latency_ms}ms")
        if alert.retrieval_scores:
            print(f"  Retrieval top-3:")
            for r in alert.retrieval_scores:
                print(f"    - {r['rule_id']:24s} score={r['score']:.3f}")
    print()


if __name__ == "__main__":
    _cli()
