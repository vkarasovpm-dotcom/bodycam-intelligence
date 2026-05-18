"""SENTINEL LivePipeline — three-layer real-time-style audit orchestrator.

Architecture:

    LAYER 1 — RAPID (per utterance, <3s, on critical path)
        Router → Retrieval → RapidProsecution → rapid_alert event
        Catches explicit triggers (threats, Miranda declarations, force)

    LAYER 2 — DEEP (every N utterances or T seconds, 30-60s, background)
        ProsecutionAgent(full transcript) → DefenseAgent → deep_violations
        Catches pattern violations only visible across the whole conversation

    LAYER 3 — CONSOLIDATION (debounced, ~2-3s, background)
        JudgeAgent(rapid + deep + rebuttals) → verdict_timeline snapshot
        Produces a continuously-evolving "current state of the case"

Public API:
    pipe = LivePipeline(session_id, region, on_event=callback)
    await pipe.run_from_replay(transcript_path, real_time=True)
    pipe.to_dict()
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from agents.base import Trace
from agents.retrieval_agent import RetrievalAgent
from agents.router_agent import RouterAgent
from agents.rapid_prosecution import RapidProsecutionAgent
from agents.replay_transcription_agent import ReplayTranscriptionAgent, Utterance

log = logging.getLogger("sentinel.pipeline_live")

EventCallback = Callable[[dict], Awaitable[None]]

# ---- Layer-1 settings ----
CONTEXT_WINDOW_SIZE = 15

# ---- Layer-2 settings ----
DEEP_SCAN_EVERY_N_UTTERANCES = 10   # trigger deep scan after this many new utts
DEEP_SCAN_EVERY_N_SECONDS    = 60.0 # OR this many wall-clock seconds, whichever first

# ---- Layer-3 settings ----
JUDGE_DEBOUNCE_SEC = 2.5            # wait this long after the last event before judging
JUDGE_IDLE_TRIGGER_SEC = 30.0       # if no events for this long, judge anyway


@dataclass
class SessionEvent:
    t: float
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


class LivePipeline:
    def __init__(
        self,
        session_id: str,
        region: str = "us",
        vertical: str = "police",
        retrieval: Optional[RetrievalAgent] = None,
        on_event: Optional[EventCallback] = None,
        audio_file: Optional[str] = None
    ):
        self.session_id = session_id
        self.region = region.lower()
        self.vertical = vertical.lower()
        self.trace = Trace()

        # Layer-1 agents (light, on critical path)
        self.retrieval = retrieval or RetrievalAgent(trace=self.trace)
        self.router = RouterAgent(region=self.region, trace=self.trace)
        self.rapid = RapidProsecutionAgent(
            region=self.region, trace=self.trace, retrieval=self.retrieval
        )

        # Layer-2 & 3 agents are imported lazily to avoid circular costs
        self._pros_agent = None
        self._def_agent = None
        self._judge_agent = None

        self.on_event = on_event
        self.audio_file = audio_file  # optional path to .mp4 for vision

        # Session state
        self.events: list[SessionEvent] = []
        self.utterances_collected: list[dict] = []  # in transcription_result format
        self.visual_context: Optional[dict] = None  # set by _run_vision_async when ready
        self._vision_task: Optional[asyncio.Task] = None
        self._vision_started: bool = False
        self.context: list[str] = []
        self.rapid_alerts: list[dict] = []

        # Layer-2 state
        self.deep_violations: list[dict] = []
        self.rebuttals: list[dict] = []
        self.last_deep_summary: str = ""
        self.last_defense_summary: str = ""
        self._deep_scan_task: Optional[asyncio.Task] = None
        self._utterances_since_last_deep = 0
        self._last_deep_scan_t: float = 0.0

        # Layer-3 state
        self.verdict_timeline: list[dict] = []
        self._judge_task: Optional[asyncio.Task] = None

        self.t0: float = time.perf_counter()
        self.meta: dict[str, Any] = {
            "session_id": session_id,
            "region": self.region,
            "vertical": self.vertical,
            "started_at": time.time(),
        }

    # ------------------------------------------------------------------
    # Lazy agent loaders
    # ------------------------------------------------------------------
    def _get_pros_agent(self):
        if self._pros_agent is None:
            from agents.prosecution_agent import ProsecutionAgent
            self._pros_agent = ProsecutionAgent(region=self.region, vertical=self.vertical)
        return self._pros_agent

    def _get_def_agent(self):
        if self._def_agent is None:
            from agents.defense_agent import DefenseAgent
            self._def_agent = DefenseAgent(region=self.region, vertical=self.vertical)
        return self._def_agent

    def _get_judge_agent(self):
        if self._judge_agent is None:
            from agents.judge_agent import JudgeAgent
            self._judge_agent = JudgeAgent(region=self.region, vertical=self.vertical)
        return self._judge_agent

    # ------------------------------------------------------------------
    # Event plumbing
    # ------------------------------------------------------------------
    async def _emit(self, kind: str, data: dict) -> None:
        evt = SessionEvent(t=time.perf_counter() - self.t0, kind=kind, data=data)
        self.events.append(evt)
        if self.on_event is not None:
            try:
                await self.on_event({"t": evt.t, "kind": evt.kind, **evt.data})
            except Exception as e:
                log.warning(f"on_event callback failed: {e}")

    def _build_transcription_result(self) -> dict:
        """Build a dict that ProsecutionAgent / DefenseAgent / JudgeAgent
        accept as `transcription_result`. Same shape as council JSON's
        `transcription` field.
        """
        result = {
            "language": self.meta.get("language", "en"),
            "target_language": None,
            "utterances": self.utterances_collected,
            "speakers": sorted({u.get("speaker", "S1") for u in self.utterances_collected}),
            "summary": self.last_deep_summary or "",
            "topics": [],
            "raw_text": "\n".join(
                f"[{u.get('speaker','?')}] {u.get('text','')}"
                for u in self.utterances_collected
            ),
            "duration_sec": (
                max((u.get("end", 0.0) for u in self.utterances_collected), default=0.0)
                if self.utterances_collected else 0.0
            ),
        }
        if self.visual_context:
            result["visual_context"] = self.visual_context
        return result

    # ==================================================================
    # LAYER 1 — RAPID
    # ==================================================================
    async def on_utterance(self, utt: Utterance) -> Optional[dict]:
        t_atom = time.perf_counter()

        # Record in transcription_result-shape for layers 2 & 3
        utt_dict = {
            "speaker": utt.speaker,
            "text": utt.text,
            "start": utt.t_start,
            "end": utt.t_end,
            "translation": None,
            "sentiment": "neutral",
            "confidence": 1.0,
        }
        self.utterances_collected.append(utt_dict)
        self._utterances_since_last_deep += 1

        await self._emit("utterance", {
            "text": utt.text, "speaker": utt.speaker,
            "t_start": utt.t_start, "t_end": utt.t_end,
            "utt_index": utt.utt_index,
        })

        # Router classification (may be sync or async)
        cls = self.router.classify(utt.text, self.context)
        if asyncio.iscoroutine(cls):
            cls = await cls

        self.context.append(utt.text)
        if len(self.context) > CONTEXT_WINDOW_SIZE:
            self.context = self.context[-CONTEXT_WINDOW_SIZE:]

        alert_dict: Optional[dict] = None
        if cls.classification == "none":
            await self._emit("router_skip", {
                "utt_index": utt.utt_index,
                "classification": cls.classification,
                "confidence": cls.confidence,
            })
        else:
            alert = self.rapid.run(
                utterance=utt.text,
                context=self.context[:-1],
                classification=cls.classification,
                query_rewrite=cls.query_rewrite,
            )
            atom_ms = int((time.perf_counter() - t_atom) * 1000)
            if alert is None:
                await self._emit("router_skip", {
                    "utt_index": utt.utt_index,
                    "classification": cls.classification,
                    "reason": "prosecution_no_alert",
                    "atom_ms": atom_ms,
                })
            else:
                alert_dict = alert.__dict__ if hasattr(alert, "__dict__") else dict(alert)
                alert_dict["utt_index"] = utt.utt_index
                alert_dict["t_utterance"] = utt.t_start
                alert_dict["atom_ms"] = atom_ms
                self.rapid_alerts.append(alert_dict)
                await self._emit("rapid_alert", alert_dict)
                # New alert → re-trigger Judge
                self._schedule_judge_update()

        # Check Layer-2 trigger conditions
        await self._maybe_trigger_deep_scan()
        return alert_dict

    # ==================================================================
    # LAYER 2 — DEEP SCAN (background)
    # ==================================================================

    # ==================================================================
    # VISION (Layer 1.5) — runs once, parallel to Layer 2
    # ==================================================================
    async def _ensure_vision_started(self):
        """Kick off background vision analysis on first call. No-op afterwards."""
        if self._vision_started or not self.audio_file:
            return
        self._vision_started = True
        self._vision_task = asyncio.create_task(self._run_vision_async())

    async def _run_vision_async(self):
        try:
            from agents.visual_context_agent import VisualContextAgent
            from agents.base import Trace
            vision_trace = Trace()
            agent = VisualContextAgent(trace=vision_trace)
            log.info(f"[{self.session_id}] vision started on {self.audio_file}")
            ctx = await asyncio.to_thread(agent.run, self.audio_file)
            self.visual_context = ctx.to_dict()
            await self._emit("visual_context_ready", {
                "force_observed": ctx.force_observed,
                "restraints_visible": ctx.restraints_visible,
                "restraints_timing": ctx.restraints_timing,
                "weapons_drawn": ctx.weapons_drawn_by_officer,
                "subject_compliance": ctx.subject_compliance,
                "key_moments": len(ctx.key_moments),
                "summary": ctx.summary[:200] if ctx.summary else "",
                "model_used": ctx.model_used,
                "latency_ms": ctx.latency_ms,
            })
            log.info(f"[{self.session_id}] vision done: force={ctx.force_observed} restraints={ctx.restraints_visible}")
        except Exception as e:
            log.warning(f"[{self.session_id}] vision failed: {e}")
            await self._emit("visual_context_failed", {"error": str(e)[:300]})

    async def _maybe_trigger_deep_scan(self):
        now = time.perf_counter() - self.t0
        triggers: list[str] = []
        if self._utterances_since_last_deep >= DEEP_SCAN_EVERY_N_UTTERANCES:
            triggers.append(f"+{self._utterances_since_last_deep}_utts")
        if self._last_deep_scan_t > 0 and (now - self._last_deep_scan_t) >= DEEP_SCAN_EVERY_N_SECONDS:
            triggers.append(f"+{int(now - self._last_deep_scan_t)}s")
        if not triggers:
            return

        # If a deep scan is already running, skip this trigger
        if self._deep_scan_task is not None and not self._deep_scan_task.done():
            await self._emit("deep_scan_skipped", {"reason": "previous_still_running",
                                                   "triggers": triggers})
            return

        # Reset trigger counters NOW (so concurrent on_utterance calls don't retrigger)
        self._utterances_since_last_deep = 0
        self._last_deep_scan_t = now

        await self._emit("deep_scan_started", {"triggers": triggers,
                                                "utterances": len(self.utterances_collected)})
        self._deep_scan_task = asyncio.create_task(self._run_deep_scan())

    async def _run_deep_scan(self):
        # Kick off vision in background if not yet started — runs parallel to deep scan
        await self._ensure_vision_started()
        # If vision task is still running, wait briefly so its results land in time
        if self._vision_task and not self._vision_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._vision_task), timeout=45.0)
            except asyncio.TimeoutError:
                log.info(f"[{self.session_id}] vision still running, proceeding without it")
            except Exception:
                pass
        """Background full Prosecution + Defense pass over accumulated transcript."""
        t_start = time.perf_counter()
        try:
            tr = self._build_transcription_result()
            if not tr["utterances"]:
                return

            # Run Prosecution + Defense in a worker thread (their LLM calls are sync)
            pros_agent = self._get_pros_agent()
            def_agent = self._get_def_agent()

            pros_report = await asyncio.to_thread(pros_agent.run, tr)
            pros_dict = pros_report.to_dict()
            self.last_deep_summary = pros_dict.get("summary", "")

            def_report = await asyncio.to_thread(def_agent.run, tr, pros_dict)
            def_dict = def_report.to_dict()
            self.last_defense_summary = def_dict.get("overall_defense_summary", "")

            # Store snapshots
            self.deep_violations = pros_dict.get("violations", []) or []
            self.rebuttals = def_dict.get("rebuttals", []) or []

            wall_ms = int((time.perf_counter() - t_start) * 1000)
            await self._emit("deep_scan_completed", {
                "wall_ms": wall_ms,
                "violations": len(self.deep_violations),
                "rebuttals": len(self.rebuttals),
                "prosecution_verdict": pros_dict.get("verdict"),
                "overall_severity": pros_dict.get("overall_severity"),
            })
            # Deep scan finished → re-judge
            self._schedule_judge_update()
        except Exception as e:
            log.error(f"deep_scan failed: {e}", exc_info=True)
            await self._emit("deep_scan_failed", {"error": str(e)[:200]})

    # ==================================================================
    # LAYER 3 — JUDGE CONSOLIDATION (debounced background)
    # ==================================================================
    def _schedule_judge_update(self):
        """Debounced: cancel any pending Judge run, schedule a new one."""
        if self._judge_task is not None and not self._judge_task.done():
            self._judge_task.cancel()
        self._judge_task = asyncio.create_task(self._delayed_judge_run())

    async def _delayed_judge_run(self):
        try:
            await asyncio.sleep(JUDGE_DEBOUNCE_SEC)
        except asyncio.CancelledError:
            return
        await self._run_judge_consolidation(reason="debounced")

    async def _run_judge_consolidation(self, reason: str = "manual"):
        t_start = time.perf_counter()
        try:
            # Build inputs in the shape JudgeAgent expects
            tr = self._build_transcription_result()

            # Merge rapid_alerts into deep_violations for Judge:
            # Judge sees the prosecution_report from a single combined source.
            # Rapid alerts are translated into pseudo-violations so they're not lost.
            combined_violations = list(self.deep_violations)
            existing_rules = {v.get("rule_id") for v in combined_violations}
            for a in self.rapid_alerts:
                rid = a.get("rule_id")
                if rid and rid not in existing_rules:
                    combined_violations.append({
                        "rule_id": rid,
                        "title": a.get("rule_title", a.get("title", rid)),
                        "source": a.get("rule_source", a.get("source", "")),
                        "severity": a.get("severity", "medium"),
                        "cited_utterances": [a.get("utt_index")] if a.get("utt_index") is not None else [],
                        "rationale": (
                            a.get("one_liner")
                            or a.get("triggering_quote")
                            or f"Rapid layer-1 alert at t={a.get('t_utterance', 0):.1f}s"
                        ),
                        "confidence": a.get("confidence", 0.7),
                    })
                    existing_rules.add(rid)

            pros_dict = {
                "verdict": "violations_present" if combined_violations else "no_violations",
                "overall_severity": self._max_severity(combined_violations),
                "violations": combined_violations,
                "summary": self.last_deep_summary,
            }
            def_dict = {
                "rebuttals": self.rebuttals,
                "overall_defense_summary": self.last_defense_summary,
            }

            judge_agent = self._get_judge_agent()
            verdict_obj = await asyncio.to_thread(
                judge_agent.run, tr, pros_dict, def_dict
            )
            verdict = verdict_obj.to_dict() if hasattr(verdict_obj, "to_dict") else \
                      (verdict_obj.__dict__ if hasattr(verdict_obj, "__dict__") else dict(verdict_obj))

            wall_ms = int((time.perf_counter() - t_start) * 1000)
            snapshot = {
                "at_t": time.perf_counter() - self.t0,
                "reason": reason,
                "wall_ms": wall_ms,
                "overall_verdict": verdict.get("overall_verdict"),
                "overall_severity": verdict.get("overall_severity"),
                "headline": verdict.get("headline"),
                "summary": verdict.get("summary"),
                "rulings": verdict.get("rulings", []),
                "n_violations": len(combined_violations),
                "n_rebuttals": len(self.rebuttals),
            }
            self.verdict_timeline.append(snapshot)
            await self._emit("verdict_update", snapshot)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error(f"judge consolidation failed: {e}", exc_info=True)
            await self._emit("verdict_failed", {"error": str(e)[:200]})

    @staticmethod
    def _max_severity(violations: list[dict]) -> str:
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}
        if not violations:
            return "none"
        return max(violations, key=lambda v: order.get(v.get("severity", "none"), 0)).get("severity", "none")

    # ==================================================================
    # Drivers
    # ==================================================================
    async def run_from_replay(
        self,
        transcript_path: str | Path,
        real_time: bool = True,
        speed: float = 1.0,
        finalize: bool = True,
    ) -> dict:
        agent = ReplayTranscriptionAgent(transcript_path)
        self.meta["transcript_path"] = str(transcript_path)
        self.meta["total_utterances"] = len(agent.utterances)

        async for utt in agent.stream(real_time=real_time, speed=speed):
            await self.on_utterance(utt)

        if finalize:
            await self.finalize()
        return self.to_dict()

    async def finalize(self):
        """Force one final deep scan + judge consolidation at session end."""
        await self._emit("session_finalizing", {})

        # Wait for any in-flight deep scan
        if self._deep_scan_task is not None and not self._deep_scan_task.done():
            try:
                await self._deep_scan_task
            except Exception:
                pass

        # Force one final deep scan (full pipeline on full transcript)
        self._utterances_since_last_deep = 0
        self._last_deep_scan_t = time.perf_counter() - self.t0
        await self._emit("deep_scan_started", {"triggers": ["session_end"],
                                                "utterances": len(self.utterances_collected)})
        await self._run_deep_scan()

        # Cancel pending debounced judge, run one final consolidation synchronously
        if self._judge_task is not None and not self._judge_task.done():
            self._judge_task.cancel()
            try:
                await self._judge_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._run_judge_consolidation(reason="session_end")

    # ==================================================================
    # Serialization
    # ==================================================================
    def to_dict(self) -> dict:
        final_verdict = self.verdict_timeline[-1] if self.verdict_timeline else None
        return {
            "session_id": self.session_id,
            "region": self.region,
            "vertical": self.vertical,
            "meta": self.meta,
            "rapid_alerts": self.rapid_alerts,
            "visual_context": self.visual_context,
            "deep_violations": self.deep_violations,
            "rebuttals": self.rebuttals,
            "verdict_timeline": self.verdict_timeline,
            "final_verdict": final_verdict,
            "events": [
                {"t": e.t, "kind": e.kind, **e.data} for e in self.events
            ],
            "stats": {
                "total_utterances": len(self.utterances_collected),
                "rapid_alerts": len(self.rapid_alerts),
                "deep_violations": len(self.deep_violations),
                "rebuttals": len(self.rebuttals),
                "verdict_snapshots": len(self.verdict_timeline),
                "router_skips": sum(1 for e in self.events if e.kind == "router_skip"),
            },
        }

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        log.info(f"[{self.session_id}] session saved → {out}")
        return out


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", help="Path to council JSON or transcript JSON")
    parser.add_argument("--session-id", default="smoke")
    parser.add_argument("--region", default="us", choices=["us", "eu", "it"])
    parser.add_argument("--real-time", action="store_true")
    parser.add_argument("--speed", type=float, default=8.0)
    parser.add_argument("--no-finalize", action="store_true",
                        help="Skip the final deep scan + judge consolidation")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def _on_event(evt: dict) -> None:
        t = evt.get("t", 0.0)
        kind = evt.get("kind", "?")
        if kind == "utterance":
            print(f"  [t+{t:5.1f}s] UTT     {evt.get('speaker','?'):4s} | {evt.get('text','')[:80]}")
        elif kind == "rapid_alert":
            print(f"  [t+{t:5.1f}s] ⚠ RAPID  [{evt.get('severity','?'):8s}] "
                  f"{evt.get('rule_id','?')} — {str(evt.get('one_liner',''))[:80]}")
        elif kind == "deep_scan_started":
            print(f"  [t+{t:5.1f}s] 🔍 DEEP-START  triggers={evt.get('triggers')} "
                  f"utts={evt.get('utterances')}")
        elif kind == "deep_scan_completed":
            print(f"  [t+{t:5.1f}s] 🔍 DEEP-DONE   {evt.get('wall_ms')}ms  "
                  f"violations={evt.get('violations')} rebuttals={evt.get('rebuttals')} "
                  f"severity={evt.get('overall_severity')}")
        elif kind == "verdict_update":
            print(f"  [t+{t:5.1f}s] ⚖ VERDICT  severity={evt.get('overall_severity')} "
                  f"verdict={evt.get('overall_verdict')}")
            hl = evt.get("headline")
            if hl: print(f"             headline: {hl[:110]}")

    async def main():
        pipe = LivePipeline(
            session_id=args.session_id,
            region=args.region,
            on_event=_on_event,
        )
        await pipe.run_from_replay(
            args.transcript,
            real_time=args.real_time,
            speed=args.speed,
            finalize=not args.no_finalize,
        )
        d = pipe.to_dict()
        print(f"\nSTATS  utts={d['stats']['total_utterances']}  "
              f"rapid={d['stats']['rapid_alerts']}  "
              f"deep_viol={d['stats']['deep_violations']}  "
              f"rebuttals={d['stats']['rebuttals']}  "
              f"verdict_snaps={d['stats']['verdict_snapshots']}")
        if d.get("final_verdict"):
            fv = d["final_verdict"]
            print(f"FINAL  {fv.get('overall_verdict')} / {fv.get('overall_severity')}")
            if fv.get("headline"):
                print(f"       {fv['headline']}")
        if args.out:
            pipe.save(args.out)

    asyncio.run(main())
