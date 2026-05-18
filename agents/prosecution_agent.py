"""SENTINEL Prosecution Agent.

Takes a TranscriptionResult (utterances + sentiment + summary) and produces
a structured accusation: violations with cited utterances, severity, and
statute references from the rule-pack (case_law/police_{region}.json).

Primary model: openai/gpt-oss-120b via Featherless.
Fallback:      google/gemma-4-26B-A4B-it via Featherless.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from agents.base import (
    Trace,
    featherless_client,
    with_fallback,
    MODELS,
    format_visual_context,
)

CASE_LAW_DIR = Path(__file__).resolve().parent.parent / "case_law"


@dataclass
class Violation:
    rule_id: str
    title: str
    source: str
    severity: str           # low / medium / high / critical
    cited_utterances: list[int]   # indices into TranscriptionResult.utterances
    rationale: str
    confidence: float       # 0.0 – 1.0


@dataclass
class ProsecutionReport:
    region: str
    vertical: str
    verdict: str            # "violations_found" / "no_violations" / "inconclusive"
    overall_severity: str   # max severity across violations
    violations: list[Violation] = field(default_factory=list)
    summary: str = ""
    model_used: str = ""
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _load_rule_pack(region: str, vertical: str = "police") -> dict:
    path = CASE_LAW_DIR / f"{vertical}_{region}.json"
    if not path.exists():
        raise FileNotFoundError(f"Rule pack not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _format_transcript(utterances: list[dict]) -> str:
    """Render utterances for prompt: [idx] [speaker @ t_start-t_end] text (sentiment)."""
    lines = []
    for i, u in enumerate(utterances):
        spk = u.get("speaker", "S?")
        t0 = u.get("start_time", 0.0)
        t1 = u.get("end_time", 0.0)
        text = u.get("text", "").strip()
        sent = u.get("sentiment")
        sent_tag = f" [{sent}]" if sent else ""
        lines.append(f"[{i}] [{spk} @ {t0:.1f}-{t1:.1f}s]{sent_tag} {text}")
    return "\n".join(lines)


def _format_rules(rules: list[dict]) -> str:
    lines = []
    for r in rules:
        triggers = ", ".join(r.get("triggers", []))
        lines.append(
            f"- {r['id']} | {r['title']} | severity={r['severity']}\n"
            f"    source: {r['source']}\n"
            f"    summary: {r['summary']}\n"
            f"    triggers: {triggers}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the PROSECUTION agent in an adversarial AI audit of police bodycam footage.

Your job: read the transcript and identify potential VIOLATIONS of the provided legal rule-pack.
You argue for the citizen — find every plausible violation by the officer(s).
Be rigorous: each violation MUST cite specific utterance indices from the transcript.
Do not invent facts. If evidence is weak, lower the confidence; do not skip it.

Output STRICT JSON only, matching this schema:
{
  "verdict": "violations_found" | "no_violations" | "inconclusive",
  "overall_severity": "low" | "medium" | "high" | "critical",
  "summary": "<2-3 sentence prosecution summary>",
  "violations": [
    {
      "rule_id": "<from rule-pack>",
      "title": "<from rule-pack>",
      "source": "<from rule-pack>",
      "severity": "<from rule-pack>",
      "cited_utterances": [<int>, <int>, ...],
      "rationale": "<2-3 sentence argument tying utterances to rule>",
      "confidence": <float 0.0-1.0>
    }
  ]
}

No prose outside JSON. No markdown fences. JSON only.
"""


def _build_user_prompt(transcript: str, rules: str, region: str, summary: str) -> str:
    return f"""REGION: {region.upper()}
INCIDENT SUMMARY: {summary}

=== APPLICABLE RULE-PACK ===
{rules}

=== TRANSCRIPT ===
{transcript}

=== TASK ===
Identify all plausible violations. Return strict JSON per schema."""


def _call_model(client, model: str, system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=3000,
    )
    return resp.choices[0].message.content


def _parse_json(text: str) -> dict:
    """Extract JSON from model output, tolerant of stray prose."""
    text = text.strip()
    # strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    # find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")
    return json.loads(text[start : end + 1])


class ProsecutionAgent:
    def __init__(self, region: str = "us", vertical: str = "police"):
        self.region = region.lower()
        self.vertical = vertical.lower()
        self.trace = Trace()
        self.client = featherless_client()

    def run(self, transcription_result: dict) -> ProsecutionReport:
        self.trace.emit("prosecution", "session_start", data={"region": self.region, "vertical": self.vertical})

        # Load rule-pack
        try:
            pack = _load_rule_pack(self.region, self.vertical)
            self.trace.emit("prosecution", "rule_pack_loaded", data={"rules": len(pack["rules"]), "version": pack.get("version")})
        except FileNotFoundError as e:
            self.trace.emit("prosecution", "rule_pack_missing", data={"error": str(e)})
            raise

        utterances = transcription_result.get("utterances", [])
        summary = transcription_result.get("summary", "") or ""
        if not utterances:
            self.trace.emit("prosecution", "empty_transcript", data={})
            return ProsecutionReport(
                region=self.region, vertical=self.vertical,
                verdict="inconclusive", overall_severity="low",
                summary="No utterances to analyze.", trace=self.trace.to_list(),
            )

        transcript_text = _format_transcript(utterances)
        rules_text = _format_rules(pack["rules"])
        visual_block = format_visual_context(transcription_result.get("visual_context"))
        user_prompt = _build_user_prompt(transcript_text, rules_text, self.region, summary)
        if visual_block:
            user_prompt = visual_block + user_prompt
            self.trace.emit("prosecution", "visual_context_injected", data={"chars": len(visual_block)})
        self.trace.emit("prosecution", "prompt_built", data={"transcript_chars": len(transcript_text), "rules_count": len(pack["rules"])})

        # Call model with fallback
        primary = MODELS["prosecution"]
        fallback = MODELS["prosecution_alt"]

        def _primary():
            self.trace.emit("prosecution", "model_call", data={"model": primary})
            return _call_model(self.client, primary, SYSTEM_PROMPT, user_prompt), primary

        def _fallback():
            self.trace.emit("prosecution", "model_fallback", data={"model": fallback})
            return _call_model(self.client, fallback, SYSTEM_PROMPT, user_prompt), fallback

        raw, model_used = with_fallback(_primary, _fallback, self.trace, "prosecution", primary_label="gpt-oss-120b", fallback_label="gemma-4-26B")
        self.trace.emit("prosecution", "model_response", data={"model": model_used, "chars": len(raw)})

        try:
            parsed = _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            self.trace.emit("prosecution", "json_parse_error", data={"error": str(e), "raw_head": raw[:300]})
            raise

        violations = [
            Violation(
                rule_id=v.get("rule_id", "UNKNOWN"),
                title=v.get("title", ""),
                source=v.get("source", ""),
                severity=v.get("severity", "low"),
                cited_utterances=v.get("cited_utterances", []),
                rationale=v.get("rationale", ""),
                confidence=float(v.get("confidence", 0.5)),
            )
            for v in parsed.get("violations", [])
        ]
        self.trace.emit("prosecution", "violations_parsed", data={"count": len(violations)})

        report = ProsecutionReport(
            region=self.region,
            vertical=self.vertical,
            verdict=parsed.get("verdict", "inconclusive"),
            overall_severity=parsed.get("overall_severity", "low"),
            summary=parsed.get("summary", ""),
            violations=violations,
            model_used=model_used,
            trace=self.trace.to_list(),
        )
        self.trace.emit("prosecution", "session_complete", data={"violations": len(violations), "verdict": report.verdict})
        report.trace = self.trace.to_list()
        return report


# ----- CLI -----
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.prosecution_agent <transcript.json> [region=us]")
        sys.exit(1)

    transcript_path = Path(sys.argv[1])
    region = sys.argv[2] if len(sys.argv) > 2 else "us"

    with transcript_path.open(encoding="utf-8") as f:
        tr = json.load(f)

    agent = ProsecutionAgent(region=region)
    report = agent.run(tr)

    print("\n" + "=" * 70)
    print(f"PROSECUTION REPORT — region={report.region} | model={report.model_used}")
    print("=" * 70)
    print(f"Verdict: {report.verdict}  |  Overall severity: {report.overall_severity}")
    print(f"Summary: {report.summary}\n")
    for i, v in enumerate(report.violations, 1):
        print(f"  [{i}] {v.rule_id} — {v.title}  ({v.severity}, conf={v.confidence:.2f})")
        print(f"       cited utterances: {v.cited_utterances}")
        print(f"       {v.rationale}\n")

    out_path = transcript_path.with_name(transcript_path.stem + "_prosecution.json")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"✓ Saved: {out_path}")
