"""SENTINEL Defense Agent.

Adversarial counterpart to ProsecutionAgent. Takes the same transcript +
the prosecution's violations list, and for each alleged violation produces
a rebuttal: either contests the facts (wrong utterance cited), the rule's
applicability (context justifies the action), or the severity (overstated).

Primary model: google/gemma-4-31B-it via Featherless.
Fallback:      openai/gpt-oss-20b via Featherless.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

from agents.base import (
    Trace,
    featherless_client,
    with_fallback,
    MODELS,
)
from agents.prosecution_agent import _format_transcript, _load_rule_pack


@dataclass
class Rebuttal:
    challenges_rule_id: str
    stance: str                          # "rebut" | "concede" | "mitigate"
    counter_argument: str
    counter_utterances: list[int] = field(default_factory=list)
    proposed_severity_adjustment: str | None = None    # e.g. "high → medium" or None
    confidence: float = 0.5


@dataclass
class DefenseReport:
    region: str
    vertical: str
    overall_defense_summary: str = ""
    rebuttals: list[Rebuttal] = field(default_factory=list)
    model_used: str = ""
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """You are the DEFENSE agent in an adversarial AI audit of police bodycam footage.

Your job: read the transcript and the PROSECUTION's list of alleged violations.
For EACH alleged violation produce a rebuttal. You argue for the officer(s).
You may take one of three stances per violation:
  - "rebut":   the alleged violation is wrong (cite incorrect, rule misapplied, no violation occurred).
  - "mitigate": a violation may have occurred but severity is overstated or context softens it.
  - "concede":  the prosecution is correct and defense cannot challenge it credibly.

Be rigorous. Cite specific utterance indices from the transcript when supporting
your counter-argument. Do not invent facts. If your counter is weak, lower confidence.

Output STRICT JSON only, matching this schema:
{
  "overall_defense_summary": "<2-3 sentence overall defense position>",
  "rebuttals": [
    {
      "challenges_rule_id": "<rule_id from prosecution>",
      "stance": "rebut" | "mitigate" | "concede",
      "counter_argument": "<2-3 sentence rebuttal>",
      "counter_utterances": [<int>, <int>, ...],
      "proposed_severity_adjustment": "<old → new>" or null,
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
            f"- {v['rule_id']} | {v['title']} | severity={v['severity']} | confidence={v.get('confidence', 0):.2f}\n"
            f"    source: {v.get('source', '')}\n"
            f"    cited utterances: [{cited}]\n"
            f"    prosecution rationale: {v.get('rationale', '')}"
        )
    return "\n".join(lines)


def _build_user_prompt(transcript: str, violations: str, rules: str,
                       region: str, summary: str, pros_summary: str) -> str:
    return f"""REGION: {region.upper()}
INCIDENT SUMMARY: {summary}

=== APPLICABLE RULE-PACK (for context) ===
{rules}

=== PROSECUTION SUMMARY ===
{pros_summary}

=== PROSECUTION'S ALLEGED VIOLATIONS ===
{violations}

=== TRANSCRIPT ===
{transcript}

=== TASK ===
Produce a rebuttal for EACH alleged violation. Return strict JSON per schema."""


def _format_rules(rules: list[dict]) -> str:
    lines = []
    for r in rules:
        lines.append(f"- {r['id']} | {r['title']} | summary: {r['summary']}")
    return "\n".join(lines)


def _call_model(client, model: str, system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=3000,
    )
    return resp.choices[0].message.content


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


class DefenseAgent:
    def __init__(self, region: str = "us", vertical: str = "police"):
        self.region = region.lower()
        self.vertical = vertical.lower()
        self.trace = Trace()
        self.client = featherless_client()

    def run(self, transcription_result: dict, prosecution_report: dict) -> DefenseReport:
        self.trace.emit("defense", "session_start",
                        data={"region": self.region, "vertical": self.vertical})

        utterances = transcription_result.get("utterances", [])
        summary = transcription_result.get("summary", "") or ""
        violations = prosecution_report.get("violations", [])
        pros_summary = prosecution_report.get("summary", "")

        if not violations:
            self.trace.emit("defense", "no_violations_to_rebut", data={})
            return DefenseReport(
                region=self.region, vertical=self.vertical,
                overall_defense_summary="Prosecution found no violations; no defense required.",
                trace=self.trace.to_list(),
            )

        pack = _load_rule_pack(self.region, self.vertical)
        self.trace.emit("defense", "rule_pack_loaded",
                        data={"rules": len(pack["rules"]), "violations_to_rebut": len(violations)})

        transcript_text = _format_transcript(utterances)
        violations_text = _format_violations(violations)
        rules_text = _format_rules(pack["rules"])
        user_prompt = _build_user_prompt(transcript_text, violations_text, rules_text,
                                         self.region, summary, pros_summary)
        self.trace.emit("defense", "prompt_built",
                        data={"transcript_chars": len(transcript_text),
                              "violations_count": len(violations)})

        primary = MODELS["defense"]
        fallback = MODELS["defense_alt"]

        def _primary():
            return _call_model(self.client, primary, SYSTEM_PROMPT, user_prompt), primary

        def _fallback():
            return _call_model(self.client, fallback, SYSTEM_PROMPT, user_prompt), fallback

        raw, model_used = with_fallback(_primary, _fallback, self.trace, "defense",
                                        primary_label="gemma-4-31B",
                                        fallback_label="gpt-oss-20b")
        self.trace.emit("defense", "model_response",
                        data={"model": model_used, "chars": len(raw)})

        try:
            parsed = _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            self.trace.emit("defense", "json_parse_error",
                            data={"error": str(e), "raw_head": raw[:300]})
            raise

        rebuttals = [
            Rebuttal(
                challenges_rule_id=r.get("challenges_rule_id", "UNKNOWN"),
                stance=r.get("stance", "rebut"),
                counter_argument=r.get("counter_argument", ""),
                counter_utterances=r.get("counter_utterances", []),
                proposed_severity_adjustment=r.get("proposed_severity_adjustment"),
                confidence=float(r.get("confidence", 0.5)),
            )
            for r in parsed.get("rebuttals", [])
        ]
        self.trace.emit("defense", "rebuttals_parsed", data={"count": len(rebuttals)})

        report = DefenseReport(
            region=self.region,
            vertical=self.vertical,
            overall_defense_summary=parsed.get("overall_defense_summary", ""),
            rebuttals=rebuttals,
            model_used=model_used,
            trace=self.trace.to_list(),
        )
        self.trace.emit("defense", "session_complete",
                        data={"rebuttals": len(rebuttals)})
        report.trace = self.trace.to_list()
        return report


# ----- CLI -----
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m agents.defense_agent <transcript.json> <prosecution.json> [region=us]")
        sys.exit(1)

    transcript_path = Path(sys.argv[1])
    prosecution_path = Path(sys.argv[2])
    region = sys.argv[3] if len(sys.argv) > 3 else "us"

    with transcript_path.open(encoding="utf-8") as f:
        tr = json.load(f)
    with prosecution_path.open(encoding="utf-8") as f:
        pr = json.load(f)

    agent = DefenseAgent(region=region)
    report = agent.run(tr, pr)

    print("\n" + "=" * 70)
    print(f"DEFENSE REPORT — region={report.region} | model={report.model_used}")
    print("=" * 70)
    print(f"Defense summary: {report.overall_defense_summary}\n")
    stance_emoji = {"rebut": "✗", "mitigate": "~", "concede": "✓"}
    for i, r in enumerate(report.rebuttals, 1):
        em = stance_emoji.get(r.stance, "?")
        adj = f" [severity: {r.proposed_severity_adjustment}]" if r.proposed_severity_adjustment else ""
        print(f"  [{i}] {em} {r.stance.upper()} {r.challenges_rule_id}  (conf={r.confidence:.2f}){adj}")
        print(f"       counter utterances: {r.counter_utterances}")
        print(f"       {r.counter_argument}\n")

    out_path = transcript_path.with_name(transcript_path.stem + "_defense.json")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"✓ Saved: {out_path}")
