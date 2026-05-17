"""SENTINEL — shared agent base, unified trace event format, fallback wrapper."""
from __future__ import annotations
import os
import time
import json
import logging
from typing import Any, Callable, Optional
from dataclasses import dataclass, asdict, field

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
    """Google Gemini client."""
    from google import genai
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

def mistral_client():
    """Mistral fallback client."""
    from mistralai import Mistral
    return Mistral(api_key=os.environ["MISTRAL_API_KEY"])


# ============ MODEL ROSTER (Featherless, non-Chinese, May 2026) ============

MODELS = {

    "router":      "google/gemma-4-E4B-it",          # 4B fast, classification
    "prosecution": "google/gemma-4-26B-A4B-it",      # 26B MoE strong reasoning
    "defense":     "google/gemma-4-31B-it",          # 31B different family for diversity
    "routing":     "openai/gpt-oss-20b",             # OSS 20B, decision routing
    "ensemble":    "meta-llama/Llama-3.1-8B-Instruct",  # Llama for ensemble vote
    # Gemini — direct API
    "judge":       "gemini-3-pro-preview",
    "vision":      "gemini-3-pro-preview",  # vision in same model
    "fallback":    "gemini-2.5-flash",      # cheap fallback
}