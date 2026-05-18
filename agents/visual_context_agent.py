"""
Visual Context Agent — Gemini 3.1 Pro video analysis for bodycam footage.

Analyzes a bodycam .mp4 (or .mp3 → no, video only) and extracts visual facts
that audio-only pipelines cannot see:
  - subjects visible (count, posture)
  - restraints (handcuffs on subject?)
  - weapons visible (officer drawn? subject armed?)
  - force observed (strikes, takedowns, ground control)
  - injuries (blood, swelling)
  - environment (street / vehicle / indoor)
  - key moments with timestamps

These facts then feed Prosecution/Defense/Judge so they can reason about
e.g. "force on a handcuffed subject" (Bouyid v Belgium) or "officer drew
weapon without articulable threat" — things impossible to detect from
transcript alone.

Primary model: gemini-3.1-pro-preview (deep visual reasoning).
Fallback:      gemini-3.1-flash-lite (rate-limit safety net).

Usage:
    python -m agents.visual_context_agent recordings/video2_violation.mp4 \\
        --out results/visual/video2_violation.json

    # In Python:
    from agents.visual_context_agent import VisualContextAgent
    agent = VisualContextAgent()
    ctx = agent.run("recordings/video2_violation.mp4")
    print(ctx.summary)
"""
from __future__ import annotations
import argparse
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import os
import subprocess
from agents.base import Trace, gemini_client, with_fallback, MODELS
from google.genai import types as _genai_types


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class KeyMoment:
    t_seconds: float
    description: str
    significance: str  # "neutral" | "concerning" | "violation_indicator" | "exculpatory"


@dataclass
class VisualContext:
    video_path: str
    duration_sec: float
    # High-level observations
    subjects_visible: int                  # number of citizens/suspects
    officers_visible: int                  # number of officers
    environment: str                       # "street_daylight" | "vehicle_interior" | "indoor_residence" | ...
    # Critical visual facts
    restraints_visible: bool               # handcuffs / zip-ties on subject
    restraints_timing: Optional[float]     # t_seconds when first applied
    weapons_drawn_by_officer: bool         # firearm/taser drawn
    weapon_type: Optional[str]             # "firearm" | "taser" | "baton" | None
    subject_armed: bool                    # weapon visible on subject
    force_observed: bool                   # strikes/takedowns/ground control
    force_description: str                 # short prose if force_observed
    injuries_visible: bool                 # blood / swelling / distress
    subject_compliance: str                # "compliant" | "passive_resistance" | "active_resistance" | "fleeing" | "mixed"
    # Bidirectional analysis
    officer_misconduct_indicators: list[str]  # short phrases
    citizen_violation_indicators: list[str]   # short phrases
    # Detailed timeline
    key_moments: list[KeyMoment] = field(default_factory=list)
    # Meta
    summary: str = ""
    model_used: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert police-accountability video analyst. You review bodycam footage to extract objective visual facts that may corroborate OR contradict allegations of misconduct.

You analyze the ENTIRE video and produce a structured JSON report.

CRITICAL RULES:
1. Report ONLY what is visually verifiable. Do not infer intent.
2. If a fact is uncertain, set the field to false / null / "unknown" — do NOT guess.
3. Be bidirectional: note BOTH officer misconduct indicators AND citizen violation indicators.
4. Use seconds (float) for all timestamps.
5. Restraints = handcuffs, zip-ties, or any binding on the subject's wrists.
6. "Force" = physical strikes, takedowns, ground-control, pain compliance, tasing — NOT verbal commands.
7. Be terse: each description ≤ 120 characters.

OUTPUT SCHEMA (strict JSON, no markdown):
{
  "subjects_visible": <int>,
  "officers_visible": <int>,
  "environment": "<short label>",
  "restraints_visible": <bool>,
  "restraints_timing": <float seconds or null>,
  "weapons_drawn_by_officer": <bool>,
  "weapon_type": "<firearm|taser|baton|null>",
  "subject_armed": <bool>,
  "force_observed": <bool>,
  "force_description": "<short prose or empty>",
  "injuries_visible": <bool>,
  "subject_compliance": "<compliant|passive_resistance|active_resistance|fleeing|mixed>",
  "officer_misconduct_indicators": ["<phrase>", ...],
  "citizen_violation_indicators": ["<phrase>", ...],
  "key_moments": [
    {"t_seconds": <float>, "description": "<what happens>", "significance": "<neutral|concerning|violation_indicator|exculpatory>"},
    ...
  ],
  "summary": "<2-4 sentence neutral overview of the encounter>"
}

Aim for 5-12 key_moments covering: initial contact, escalation points, use of force (if any), restraint application (if any), resolution."""


USER_PROMPT = """Analyze this bodycam footage and produce the structured JSON report.

Pay particular attention to:
- WHEN the subject became restrained (if at all) — and whether any force was applied AFTER restraint (this is a critical legal indicator under ECHR Art. 3 / Bouyid v Belgium and US 4th Amendment excessive-force doctrine).
- WHETHER the officer drew a weapon, and what the subject was doing at that moment.
- WHETHER the subject was complying, passively resisting, actively resisting, or fleeing.
- Visible injuries to either party.

Return ONLY the JSON object — no preamble, no markdown fences."""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class VisualContextAgent:
    GCS_BUCKET = os.environ.get("SENTINEL_GCS_BUCKET", "sentinel-bodycam-0620148a")

    def __init__(self, trace: Optional[Trace] = None):
        self.trace = trace or Trace()
        # Vertex AI client (uses ADC + GCP_PROJECT_ID/GCP_LOCATION). Videos
        # are passed via gs:// URIs because Vertex does not support the
        # Files API — videos must live in GCS.
        self.client = gemini_client()
        self.primary_model = MODELS.get("vision", "gemini-3.1-pro-preview")
        self.fallback_model = MODELS.get("fallback", "gemini-3.1-flash-lite")

    def _ensure_in_gcs(self, video_path: str) -> str:
        """Ensure the video lives in GCS; return gs:// URI.

        If the path is already a gs:// URI, return as-is.
        Otherwise: check if blob exists in self.GCS_BUCKET (by basename);
        if not, upload via gsutil cp.
        """
        # Already a GCS URI?
        if video_path.startswith("gs://"):
            self.trace.emit("vision", "gcs_uri_passthrough", data={"uri": video_path})
            return video_path

        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        blob_name = path.name
        gcs_uri = f"gs://{self.GCS_BUCKET}/{blob_name}"
        size_mb = path.stat().st_size / (1024 * 1024)

        # Check if already uploaded
        check = subprocess.run(
            ["gsutil", "-q", "stat", gcs_uri],
            capture_output=True, text=True,
        )
        if check.returncode == 0:
            self.trace.emit("vision", "gcs_cached", data={"uri": gcs_uri, "size_mb": round(size_mb, 1)})
            return gcs_uri

        # Upload
        self.trace.emit("vision", "gcs_upload_start", data={"path": str(path), "size_mb": round(size_mb, 1), "uri": gcs_uri})
        t0 = time.perf_counter()
        up = subprocess.run(
            ["gsutil", "cp", str(path), gcs_uri],
            capture_output=True, text=True,
        )
        if up.returncode != 0:
            raise RuntimeError(f"gsutil cp failed: {up.stderr[:300]}")
        elapsed = (time.perf_counter() - t0) * 1000
        self.trace.emit("vision", "gcs_upload_complete", data={"uri": gcs_uri, "wall_ms": round(elapsed, 0)})
        return gcs_uri

    def _call_model(self, model: str, gcs_uri: str) -> str:
        """Run generate_content with a GCS video URI + prompts."""
        video_part = _genai_types.Part.from_uri(
            file_uri=gcs_uri,
            mime_type="video/mp4",
        )
        resp = self.client.models.generate_content(
            model=model,
            contents=[
                video_part,
                SYSTEM_PROMPT + "\n\n" + USER_PROMPT,
            ],
            config={
                "temperature": 0.2,
                "max_output_tokens": 6000,
                "response_mime_type": "application/json",
            },
        )
        return resp.text or ""

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip("` \n")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON object in model output: {text[:200]}")
        return json.loads(text[start:end + 1])

    def run(self, video_path: str) -> VisualContext:
        t_start = time.perf_counter()
        self.trace.emit("vision", "session_start", data={"video": video_path})

        # 1. Ensure video is in GCS (uploads if needed, otherwise cached)
        gcs_uri = self._ensure_in_gcs(video_path)

        # 2. Call primary, fallback if needed
        def _primary():
            return self._call_model(self.primary_model, gcs_uri), self.primary_model

        def _fallback():
            return self._call_model(self.fallback_model, gcs_uri), self.fallback_model

        raw, model_used = with_fallback(
            _primary, _fallback, self.trace, "vision",
            primary_label=self.primary_model,
            fallback_label=self.fallback_model,
        )

        self.trace.emit("vision", "model_response",
                        data={"model": model_used, "chars": len(raw)})

        # 3. Parse JSON
        try:
            parsed = self._parse_json(raw)
        except Exception as e:
            self.trace.emit("vision", "parse_failed", data={"error": str(e), "raw_head": raw[:300]})
            raise

        # 4. Build VisualContext
        key_moments = [
            KeyMoment(
                t_seconds=float(m.get("t_seconds", 0.0)),
                description=str(m.get("description", ""))[:200],
                significance=str(m.get("significance", "neutral")),
            )
            for m in parsed.get("key_moments", []) or []
        ]

        # Determine duration (best-effort via ffprobe if available)
        duration = 0.0
        try:
            import subprocess
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=5,
            )
            duration = float(out.stdout.strip() or 0.0)
        except Exception:
            pass

        ctx = VisualContext(
            video_path=video_path,
            duration_sec=duration,
            subjects_visible=int(parsed.get("subjects_visible", 0) or 0),
            officers_visible=int(parsed.get("officers_visible", 0) or 0),
            environment=str(parsed.get("environment", "unknown")),
            restraints_visible=bool(parsed.get("restraints_visible", False)),
            restraints_timing=parsed.get("restraints_timing"),
            weapons_drawn_by_officer=bool(parsed.get("weapons_drawn_by_officer", False)),
            weapon_type=parsed.get("weapon_type"),
            subject_armed=bool(parsed.get("subject_armed", False)),
            force_observed=bool(parsed.get("force_observed", False)),
            force_description=str(parsed.get("force_description", ""))[:500],
            injuries_visible=bool(parsed.get("injuries_visible", False)),
            subject_compliance=str(parsed.get("subject_compliance", "unknown")),
            officer_misconduct_indicators=list(parsed.get("officer_misconduct_indicators", []) or []),
            citizen_violation_indicators=list(parsed.get("citizen_violation_indicators", []) or []),
            key_moments=key_moments,
            summary=str(parsed.get("summary", ""))[:1500],
            model_used=model_used,
            latency_ms=round((time.perf_counter() - t_start) * 1000, 0),
        )

        # 5. No cleanup — GCS blobs persist (cached for future runs)

        self.trace.emit("vision", "session_complete", data={
            "model": ctx.model_used,
            "force_observed": ctx.force_observed,
            "restraints_visible": ctx.restraints_visible,
            "weapons_drawn": ctx.weapons_drawn_by_officer,
            "key_moments": len(ctx.key_moments),
            "wall_ms": ctx.latency_ms,
        })
        return ctx


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Analyze bodycam video with Gemini.")
    ap.add_argument("video", help="Path to .mp4 bodycam file")
    ap.add_argument("--out", help="Save JSON output to this path")
    args = ap.parse_args()

    agent = VisualContextAgent()
    print(f"[vision] analyzing {args.video} with {agent.primary_model}...")
    ctx = agent.run(args.video)

    print()
    print("=" * 70)
    print(f"VISUAL CONTEXT — {args.video}")
    print("=" * 70)
    print(f"Duration:             {ctx.duration_sec:.1f}s")
    print(f"Model:                {ctx.model_used}")
    print(f"Latency:              {ctx.latency_ms:.0f} ms")
    print()
    print(f"Subjects visible:     {ctx.subjects_visible}")
    print(f"Officers visible:     {ctx.officers_visible}")
    print(f"Environment:          {ctx.environment}")
    print(f"Restraints visible:   {ctx.restraints_visible}  (t={ctx.restraints_timing})")
    print(f"Officer weapon drawn: {ctx.weapons_drawn_by_officer}  ({ctx.weapon_type})")
    print(f"Subject armed:        {ctx.subject_armed}")
    print(f"Force observed:       {ctx.force_observed}")
    if ctx.force_observed:
        print(f"  → {ctx.force_description}")
    print(f"Injuries visible:     {ctx.injuries_visible}")
    print(f"Subject compliance:   {ctx.subject_compliance}")
    print()
    print("Officer misconduct indicators:")
    for x in ctx.officer_misconduct_indicators:
        print(f"  - {x}")
    print("Citizen violation indicators:")
    for x in ctx.citizen_violation_indicators:
        print(f"  - {x}")
    print()
    print(f"Key moments ({len(ctx.key_moments)}):")
    for m in ctx.key_moments:
        print(f"  [{m.t_seconds:6.1f}s] {m.significance:22s} | {m.description}")
    print()
    print(f"SUMMARY: {ctx.summary}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(ctx.to_dict(), indent=2, ensure_ascii=False))
        print(f"\nSaved to: {out_path}  ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
