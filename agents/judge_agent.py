"""SENTINEL Judge Agent.

Final arbiter in the adversarial council. Reads the transcript, the
prosecution report, and the defense report, then issues a structured
verdict with per-rule rulings and a reasoning trace.

Primary model: gemini-3.1-pro-preview via google-genai.
Fallback:      gemini-3.1-flash-lite via google-genai.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

from agents.base import format_visual_context, Trace, gemini_client, with_fallback, MODELS
from agents.prosecution_agent import _format_transcript


@dataclass
class Ruling:
    rule_id: str
    title: str
    verdict: str                # "violation_upheld" | "violation_dismissed" | "violation_mitigated" | "inconclusive"
    final_severity: str         # "low" | "medium" | "high" | "critical" | "none"
    reasoning: str              # judge's per-rule rationale
    key_utterances: list[int] = field(default_factory=list)
    prosecution_weight: float = 0.5   # how persuasive prosecution was (0-1)
    defense_weight: float = 0.5       # how persuasive defense was (0-1)
    confidence: float = 0.5


@dataclass
class JudgeVerdict:
    region: str
    vertical: str
    overall_verdict: str        # "officer_at_fault" | "officer_justified" | "mixed" | "inconclusive"
    overall_severity: str       # max severity across upheld rulings
    headline: str               # 1-sentence headline for UI
    summary: str                # 3-5 sentence reasoning
    rulings: list[Ruling] = field(default_factory=list)
    model_used: str = ""
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """You are the JUDGE in an adversarial AI audit of police bodycam footage.

You have received THREE inputs:
  1. The full transcript with speaker tags and timestamps.
  2. The PROSECUTION's report (alleged violations against the officer).
  3. The DEFENSE's report (rebuttals to each violation).

Your task: weigh both sides for EACH alleged violation and issue a final ruling.

For each violation in the prosecution report, choose one outcome:
  - "violation_upheld":    prosecution's case stands; defense was unpersuasive.
  - "violation_dismissed": defense's rebuttal succeeded; no violation occurred.
  - "violation_mitigated": violation occurred but with reduced severity.
  - "inconclusive":        evidence on both sides too weak to decide.

Be impartial. Cite specific utterance indices in your reasoning when key.
Do not invent facts. Calibrate confidence honestly.

Output STRICT JSON only:
{
  "overall_verdict": "officer_at_fault" | "officer_justified" | "mixed" | "inconclusive",
  "overall_severity": "none" | "low" | "medium" | "high" | "critical",
  "headline": "<1 sentence verdict for UI display>",
  "summary": "<3-5 sentence judicial reasoning>",
  "rulings": [
    {
      "rule_id": "<from prosecution>",
      "title": "<from prosecution>",
      "verdict": "violation_upheld" | "violation_dismissed" | "violation_mitigated" | "inconclusive",
      "final_severity": "none" | "low" | "medium" | "high" | "critical",
      "reasoning": "<2-4 sentence per-rule reasoning>",
      "key_utterances": [<int>, ...],
      "prosecution_weight": <float 0.0-1.0>,
      "defense_weight": <float 0.0-1.0>,
      "confidence": <float 0.0-1.0>
    }
  ]
}

No prose outside JSON. No markdown fences. JSON only.
"""


def _format_violations(violations: list[dict]) -> str:
    lines = []
    for v in violations:
        cited = ", ".join(str(i) for i in v.get("cited_utterances", []))
        lines.append(
            f"- {v['rule_id']} | {v['title']} | severity={v['severity']} | conf={v.get('confidence', 0):.2f}\n"
            f"    cited utterances: [{cited}]\n"
            f"    rationale: {v.get('rationale', '')}"
        )
    return "\n".join(lines)


def _format_rebuttals(rebuttals: list[dict]) -> str:
    lines = []
    for r in rebuttals:
        cited = ", ".join(str(i) for i in r.get("counter_utterances", []))
        adj = r.get("proposed_severity_adjustment") or "none"
        lines.append(
            f"- challenges: {r['challenges_rule_id']} | stance={r['stance']} | conf={r.get('confidence', 0):.2f}\n"
            f"    counter utterances: [{cited}]\n"
            f"    severity adjustment: {adj}\n"
            f"    counter-argument: {r.get('counter_argument', '')}"
        )
    return "\n".join(lines)


def _build_user_prompt(transcript: str, violations: str, rebuttals: str,
                       region: str, summary: str,
                       pros_summary: str, def_summary: str) -> str:
    return f"""REGION: {region.upper()}
INCIDENT SUMMARY: {summary}

=== PROSECUTION SUMMARY ===
{pros_summary}

=== DEFENSE SUMMARY ===
{def_summary}

=== PROSECUTION'S ALLEGED VIOLATIONS ===
{violations}

=== DEFENSE'S REBUTTALS ===
{rebuttals}

=== TRANSCRIPT ===
{transcript}

=== TASK ===
For each alleged violation, weigh prosecution vs. defense and issue a final ruling.
Return strict JSON per schema."""


def _call_gemini(client, model: str, system: str, user: str) -> str:
    """Call Gemini via google-genai SDK."""
    full_prompt = system + "\n\n" + user
    resp = client.models.generate_content(
        model=model,
        contents=full_prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 4000,
        },
    )
    return resp.text


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")
    return json.loads(text[start:end + 1])


class JudgeAgent:
    def __init__(self, region: str = "us", vertical: str = "police"):
        self.region = region.lower()
        self.vertical = vertical.lower()
        self.trace = Trace()
        self.client = gemini_client()

    def run(self, transcription_result: dict,
            prosecution_report: dict,
            defense_report: dict) -> JudgeVerdict:
        self.trace.emit("judge", "session_start",
                        data={"region": self.region, "vertical": self.vertical})

        utterances = transcription_result.get("utterances", [])
        summary = transcription_result.get("summary", "") or ""
        violations = prosecution_report.get("violations", [])
        rebuttals = defense_report.get("rebuttals", [])
        pros_summary = prosecution_report.get("summary", "")
        def_summary = defense_report.get("overall_defense_summary", "")

        if not violations:
            self.trace.emit("judge", "no_case", data={})
            return JudgeVerdict(
                region=self.region, vertical=self.vertical,
                overall_verdict="officer_justified", overall_severity="none",
                headline="No alleged violations — no case to adjudicate.",
                summary="The prosecution presented no violations; the officer is presumed justified.",
                trace=self.trace.to_list(),
            )

        transcript_text = _format_transcript(utterances)
        violations_text = _format_violations(violations)
        rebuttals_text = _format_rebuttals(rebuttals)
        visual_block = format_visual_context(transcription_result.get("visual_context")) if isinstance(transcription_result, dict) else ""
        user_prompt = _build_user_prompt(transcript_text, violations_text, rebuttals_text,
                                         self.region, summary, pros_summary, def_summary)
        if visual_block:
            user_prompt = visual_block + user_prompt
            self.trace.emit("judge", "visual_context_injected", data={"chars": len(visual_block)})
        self.trace.emit("judge", "prompt_built",
                        data={"transcript_chars": len(transcript_text),
                              "violations": len(violations),
                              "rebuttals": len(rebuttals)})

        primary = MODELS["judge"]
        fallback = MODELS["fallback"]

        def _primary():
            return _call_gemini(self.client, primary, SYSTEM_PROMPT, user_prompt), primary

        def _fallback():
            return _call_gemini(self.client, fallback, SYSTEM_PROMPT, user_prompt), fallback

        raw, model_used = with_fallback(_primary, _fallback, self.trace, "judge",
                                        primary_label="gemini-3.1-pro",
                                        fallback_label="gemini-3.1-flash-lite")
        self.trace.emit("judge", "model_response",
                        data={"model": model_used, "chars": len(raw)})

        try:
            parsed = _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            self.trace.emit("judge", "json_parse_error",
                            data={"error": str(e), "raw_head": raw[:300]})
            raise

        rulings = [
            Ruling(
                rule_id=r.get("rule_id", "UNKNOWN"),
                title=r.get("title", ""),
                verdict=r.get("verdict", "inconclusive"),
                final_severity=r.get("final_severity", "low"),
                reasoning=r.get("reasoning", ""),
                key_utterances=r.get("key_utterances", []),
                prosecution_weight=float(r.get("prosecution_weight", 0.5)),
                defense_weight=float(r.get("defense_weight", 0.5)),
                confidence=float(r.get("confidence", 0.5)),
            )
            for r in parsed.get("rulings", [])
        ]
        self.trace.emit("judge", "rulings_parsed", data={"count": len(rulings)})

        verdict = JudgeVerdict(
            region=self.region,
            vertical=self.vertical,
            overall_verdict=parsed.get("overall_verdict", "inconclusive"),
            overall_severity=parsed.get("overall_severity", "low"),
            headline=parsed.get("headline", ""),
            summary=parsed.get("summary", ""),
            rulings=rulings,
            model_used=model_used,
            trace=self.trace.to_list(),
        )
        self.trace.emit("judge", "session_complete",
                        data={"overall_verdict": verdict.overall_verdict,
                              "rulings": len(rulings)})
        verdict.trace = self.trace.to_list()
        return verdict


# ----- CLI -----
if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python -m agents.judge_agent <transcript.json> <prosecution.json> <defense.json> [region=us]")
        sys.exit(1)

    transcript_path = Path(sys.argv[1])
    prosecution_path = Path(sys.argv[2])
    defense_path = Path(sys.argv[3])
    region = sys.argv[4] if len(sys.argv) > 4 else "us"

    with transcript_path.open(encoding="utf-8") as f:
        tr = json.load(f)
    with prosecution_path.open(encoding="utf-8") as f:
        pr = json.load(f)
    with defense_path.open(encoding="utf-8") as f:
        df = json.load(f)

    agent = JudgeAgent(region=region)
    verdict = agent.run(tr, pr, df)

    print("\n" + "=" * 70)
    print(f"JUDGE VERDICT — region={verdict.region} | model={verdict.model_used}")
    print("=" * 70)
    print(f"HEADLINE: {verdict.headline}")
    print(f"Overall verdict:  {verdict.overall_verdict}")
    print(f"Overall severity: {verdict.overall_severity}")
    print(f"\nSummary: {verdict.summary}\n")

    verdict_emoji = {
        "violation_upheld": "⚖️ UPHELD",
        "violation_dismissed": "✗ DISMISSED",
        "violation_mitigated": "~ MITIGATED",
        "inconclusive": "? INCONCLUSIVE",
    }
    for i, r in enumerate(verdict.rulings, 1):
        tag = verdict_emoji.get(r.verdict, r.verdict)
        print(f"  [{i}] {tag}  {r.rule_id} — {r.title}")
        print(f"       final severity: {r.final_severity}  | conf={r.confidence:.2f}")
        print(f"       weights: prosecution={r.prosecution_weight:.2f}  defense={r.defense_weight:.2f}")
        print(f"       key utterances: {r.key_utterances}")
        print(f"       {r.reasoning}\n")

    out_path = transcript_path.with_name(transcript_path.stem + "_verdict.json")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(verdict.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"✓ Saved: {out_path}")
