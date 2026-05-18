"""SENTINEL — shared agent base, unified trace event format, fallback wrapper."""
from __future__ import annotations
import os
import time
import json
import logging
from typing import Any, Callable, Optional
from dataclasses import dataclass, asdict, field

from dotenv import load_dotenv
load_dotenv(dotenv_path="/opt/sentinel/.env")

from dotenv import load_dotenv
load_dotenv(dotenv_path="/opt/sentinel/.env")

logger = logging.getLogger("sentinel.agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ============ UNIFIED TRACE EVENT ============

@dataclass
class TraceEvent:
    """Single step in the agent council's reasoning trace.
    
    Every agent writes here. UI renders by `agent` color/icon.
    """
    agent: str                          # "transcription" | "vision" | "router" | "prosecution" | "defense" | "judge"
    action: str                         # short verb: "scan_transcript", "cite_case_law", "assess_severity", "fallback_to_gemini"
    data: dict[str, Any] = field(default_factory=dict)
    reasoning: Optional[str] = None     # human-readable rationale, nullable
    video_timestamp: Optional[str] = None   # "MM:SS" if applicable
    ts_unix: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return asdict(self)


class Trace:
    """Mutable trace collector — shared across all agents per job."""
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
    
    def add(self, ev: TraceEvent) -> None:
        self._events.append(ev)
        logger.info(f"[{ev.agent}] {ev.action} {ev.data if ev.data else ''}")
    
    def emit(self, agent: str, action: str, **kwargs: Any) -> None:
        """Shortcut: trace.emit('judge', 'verdict', data={'severity':'critical'})"""
        ev = TraceEvent(agent=agent, action=action, **kwargs)
        self.add(ev)
    
    def to_list(self) -> list[dict]:
        return [ev.to_dict() for ev in self._events]
    
    def filter(self, agent: Optional[str] = None) -> list[dict]:
        if agent is None:
            return self.to_list()
        return [ev.to_dict() for ev in self._events if ev.agent == agent]


# ============ FALLBACK WRAPPER ============

class AgentError(Exception):
    pass


def with_fallback(
    primary: Callable[[], Any],
    fallback: Callable[[], Any],
    trace: Trace,
    agent_name: str,
    primary_label: str = "primary",
    fallback_label: str = "fallback",
) -> Any:
    """Try primary, on any exception log a trace event and try fallback.
    
    Used to wrap Featherless calls with Gemini/Mistral fallback so the demo
    survives rate-limits or transient API errors.
    """
    try:
        result = primary()
        trace.emit(agent_name, f"call_{primary_label}", data={"status": "ok"})
        return result
    except Exception as e:
        logger.warning(f"[{agent_name}] primary failed: {e!r}, switching to fallback")
        trace.emit(
            agent_name,
            f"fallback_to_{fallback_label}",
            data={"error": str(e)[:200]},
            reasoning=f"Primary model {primary_label} failed; using {fallback_label}.",
        )
        try:
            return fallback()
        except Exception as e2:
            logger.error(f"[{agent_name}] fallback ALSO failed: {e2!r}")
            trace.emit(agent_name, "all_failed", data={"error": str(e2)[:200]})
            raise AgentError(f"{agent_name}: both primary and fallback failed: {e2}") from e2


# ============ CLIENT FACTORIES ============

def featherless_client():
    """OpenAI-compatible client to Featherless inference."""
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["FEATHERLESS_API_KEY"],
        base_url="https://api.featherless.ai/v1",
    )

def gemini_client():
    """Google Gemini client via Vertex AI (uses ADC + GCP_PROJECT_ID)."""
    from google import genai
    project = os.environ.get("GCP_PROJECT_ID", "project-0620148a-da18-45ef-a21")
    location = os.environ.get("GCP_LOCATION", "global")
    return genai.Client(vertexai=True, project=project, location=location)

def mistral_client():
    """Mistral fallback client."""
    from mistralai import Mistral
    return Mistral(api_key=os.environ["MISTRAL_API_KEY"])


# ============ MODEL ROSTER (Featherless, non-Chinese, May 2026) ============

MODELS = {
    # Featherless (OpenAI-compatible inference) — all verified non-Chinese, Warm
    "router":          "google/gemma-4-E4B-it",
    "prosecution":     "openai/gpt-oss-120b",
    "prosecution_alt": "google/gemma-4-26B-A4B-it",
    "rapid":           "openai/gpt-oss-20b",
    "defense":         "google/gemma-4-31B-it",
    "defense_alt":     "openai/gpt-oss-20b",
    "ensemble":        "meta-llama/Llama-3.1-8B-Instruct",
    "routing":         "google/gemma-4-E4B-it",
    
    # Gemini (Google AI Studio direct API)
    "judge":    "gemini-3.1-pro-preview",
    "vision":   "gemini-3.1-pro-preview",
    "fallback": "gemini-3.1-flash-lite",
    
    # Mistral (legacy v1 + tertiary fallback)
    "legacy":   "mistral-large-latest",
}

# ---------------------------------------------------------------------------
# Visual context formatting (used by Prosecution / Defense / Judge prompts)
# ---------------------------------------------------------------------------

def format_visual_context(vc: dict | None) -> str:
    """Render a VisualContext dict as a prompt-ready block.

    Returns "" if no visual_context is available (so prompts stay clean
    when running audio-only).
    """
    if not vc or not isinstance(vc, dict):
        return ""

    lines = ["=== VISUAL CONTEXT (from bodycam video analysis by Gemini Vision) ==="]
    lines.append(
        f"Subjects: {vc.get('subjects_visible', '?')}, "
        f"Officers: {vc.get('officers_visible', '?')}, "
        f"Environment: {vc.get('environment', 'unknown')}, "
        f"Subject compliance: {vc.get('subject_compliance', 'unknown')}"
    )
    if vc.get("restraints_visible"):
        t = vc.get("restraints_timing")
        lines.append(
            f"RESTRAINTS VISIBLE: handcuffs/restraints applied"
            + (f" at t={t:.1f}s" if isinstance(t, (int, float)) else "")
        )
    if vc.get("weapons_drawn_by_officer"):
        lines.append(f"OFFICER WEAPON DRAWN: {vc.get('weapon_type', 'unspecified')}")
    if vc.get("subject_armed"):
        lines.append("SUBJECT ARMED: weapon visible on subject")
    if vc.get("force_observed"):
        lines.append(f"FORCE OBSERVED: {vc.get('force_description', '(no description)')}")
    if vc.get("injuries_visible"):
        lines.append("INJURIES VISIBLE")

    om = vc.get("officer_misconduct_indicators") or []
    cv = vc.get("citizen_violation_indicators") or []
    if om:
        lines.append("Officer misconduct indicators: " + "; ".join(str(x) for x in om))
    if cv:
        lines.append("Citizen violation indicators: " + "; ".join(str(x) for x in cv))

    km = vc.get("key_moments") or []
    if km:
        lines.append("Key visual moments (t_seconds | significance | description):")
        for m in km[:15]:
            lines.append(
                f"  [{float(m.get('t_seconds', 0)):6.1f}s] {m.get('significance','neutral'):20s} | {m.get('description','')}"
            )

    summary = vc.get("summary")
    if summary:
        lines.append(f"Visual summary: {summary}")

    lines.append("=== END VISUAL CONTEXT ===\n")
    return "\n".join(lines) + "\n"
