"""SENTINEL Council Pipeline v2.

End-to-end orchestrator: audio file → transcription → prosecution → defense → judge
→ unified CouncilReport with merged trace from all 4 agents.

Used by:
  - CLI:  python -m pipeline_v2 recordings/foo.mp3 us
  - API:  POST /api/audit/{id}/council  (see main.py)
"""
from __future__ import annotations

import json
import time
import asyncio
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from agents.base import Trace
from agents.transcription_agent import TranscriptionAgent
from agents.prosecution_agent import ProsecutionAgent
from agents.defense_agent import DefenseAgent
from agents.judge_agent import JudgeAgent


@dataclass
class CouncilReport:
    audio_file: str
    region: str
    vertical: str
    duration_sec: float
    wall_sec: float                   # total wall clock for the council
    transcription: dict = field(default_factory=dict)
    prosecution: dict = field(default_factory=dict)
    defense: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    status: str = "ok"                # "ok" | "partial" | "failed"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)



def _maybe_run_vision(audio_path: Path, merged_trace) -> dict | None:
    """If a sibling .mp4 exists for the audio, run VisualContextAgent.
    Returns visual_context dict or None.
    Controlled by env SENTINEL_VISION (default: "1" = on).
    """
    if os.environ.get("SENTINEL_VISION", "1") not in ("1", "true", "yes", "on"):
        return None
    # Look for a video sibling: same stem, .mp4
    candidates = [
        audio_path.with_suffix(".mp4"),
        audio_path.parent / (audio_path.stem + ".mp4"),
    ]
    video_path = next((p for p in candidates if p.exists()), None)
    if not video_path:
        # If the audio path IS already a video, use it directly
        if audio_path.suffix.lower() in (".mp4", ".mov", ".mkv"):
            video_path = audio_path
        else:
            merged_trace.emit("council", "vision_skipped", data={"reason": "no_video_sibling"})
            return None
    try:
        from agents.visual_context_agent import VisualContextAgent
        vision_trace = Trace()
        agent = VisualContextAgent(trace=vision_trace)
        merged_trace.emit("council", "vision_start", data={"video": str(video_path)})
        ctx = agent.run(str(video_path))
        for ev in vision_trace.to_list():
            merged_trace._events.append(_dict_to_event(ev))
        merged_trace.emit("council", "vision_done", data={
            "force_observed": ctx.force_observed,
            "restraints_visible": ctx.restraints_visible,
            "weapons_drawn": ctx.weapons_drawn_by_officer,
            "key_moments": len(ctx.key_moments),
            "model": ctx.model_used,
        })
        return ctx.to_dict()
    except Exception as e:
        merged_trace.emit("council", "vision_failed", data={"error": str(e)[:300]})
        return None


def run_council(audio_path: str | Path,
                region: str = "us",
                vertical: str = "police",
                language: str = "en",
                save: bool = True) -> CouncilReport:
    """Run the full 4-agent council on one audio file.

    Returns CouncilReport with all 4 sub-reports and merged trace.
    If `save=True`, writes JSON to results/council/{stem}_council.json.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    t0 = time.time()
    merged_trace = Trace()
    merged_trace.emit("council", "pipeline_start",
                      data={"audio": audio_path.name, "region": region, "vertical": vertical})

    report = CouncilReport(
        audio_file=str(audio_path),
        region=region,
        vertical=vertical,
        duration_sec=0.0,
        wall_sec=0.0,
    )

    # ----- 1. Transcription + Vision (parallel via threads) -----
    visual_context_dict: dict | None = None
    try:
        from concurrent.futures import ThreadPoolExecutor

        trans_trace = Trace()
        trans_agent = TranscriptionAgent(
            trace=trans_trace,
            language=language,
            enable_sentiment=True,
            enable_summary=True,
            enable_topics=True,
            realtime_factor=8.0,
        )

        def _run_transcription():
            return asyncio.run(trans_agent.transcribe_file(str(audio_path)))

        def _run_vision():
            return _maybe_run_vision(audio_path, merged_trace)

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_trans = pool.submit(_run_transcription)
            fut_vision = pool.submit(_run_vision)
            trans_result = fut_trans.result()
            try:
                visual_context_dict = fut_vision.result()
            except Exception as e:
                merged_trace.emit("council", "vision_failed", data={"error": str(e)[:300]})
                visual_context_dict = None

        report.transcription = asdict(trans_result)
        # Inject visual_context into transcription dict so Prosecution/Defense/Judge see it
        if visual_context_dict:
            report.transcription["visual_context"] = visual_context_dict
        report.duration_sec = trans_result.duration_sec
        for ev in trans_trace.to_list():
            merged_trace._events.append(_dict_to_event(ev))
        merged_trace.emit("council", "transcription_done",
                          data={"utterances": len(trans_result.utterances),
                                "speakers": len(trans_result.speakers),
                                "visual_context": bool(visual_context_dict)})
    except Exception as e:
        merged_trace.emit("council", "transcription_failed", data={"error": str(e)[:300]})
        report.status = "failed"
        report.error = f"transcription: {e}"
        report.trace = merged_trace.to_list()
        if save:
            _save_report(report, audio_path)
        return report

    # ----- 2. Prosecution -----
    try:
        pros_agent = ProsecutionAgent(region=region, vertical=vertical)
        pros_report = pros_agent.run(report.transcription)
        report.prosecution = pros_report.to_dict()
        for ev in pros_report.trace:
            merged_trace._events.append(_dict_to_event(ev))
        merged_trace.emit("council", "prosecution_done",
                          data={"violations": len(pros_report.violations),
                                "verdict": pros_report.verdict})
    except Exception as e:
        merged_trace.emit("council", "prosecution_failed", data={"error": str(e)[:300]})
        report.status = "partial"
        report.error = f"prosecution: {e}"
        report.trace = merged_trace.to_list()
        if save:
            _save_report(report, audio_path)
        return report

    # ----- 3. Defense -----
    try:
        def_agent = DefenseAgent(region=region, vertical=vertical)
        def_report = def_agent.run(report.transcription, report.prosecution)
        report.defense = def_report.to_dict()
        for ev in def_report.trace:
            merged_trace._events.append(_dict_to_event(ev))
        merged_trace.emit("council", "defense_done",
                          data={"rebuttals": len(def_report.rebuttals)})
    except Exception as e:
        merged_trace.emit("council", "defense_failed", data={"error": str(e)[:300]})
        report.status = "partial"
        report.error = f"defense: {e}"
        report.trace = merged_trace.to_list()
        if save:
            _save_report(report, audio_path)
        return report

    # ----- 4. Judge -----
    try:
        judge_agent = JudgeAgent(region=region, vertical=vertical)
        verdict = judge_agent.run(report.transcription, report.prosecution, report.defense)
        report.verdict = verdict.to_dict()
        for ev in verdict.trace:
            merged_trace._events.append(_dict_to_event(ev))
        merged_trace.emit("council", "judge_done",
                          data={"overall_verdict": verdict.overall_verdict,
                                "overall_severity": verdict.overall_severity,
                                "rulings": len(verdict.rulings)})
    except Exception as e:
        merged_trace.emit("council", "judge_failed", data={"error": str(e)[:300]})
        report.status = "partial"
        report.error = f"judge: {e}"
        report.trace = merged_trace.to_list()
        if save:
            _save_report(report, audio_path)
        return report

    # ----- Done -----
    report.wall_sec = round(time.time() - t0, 2)
    merged_trace.emit("council", "pipeline_complete",
                      data={"wall_sec": report.wall_sec, "status": "ok"})
    report.trace = merged_trace.to_list()
    if save:
        _save_report(report, audio_path)
    return report


def _dict_to_event(ev_dict: dict):
    """Reconstruct TraceEvent from its dict form (used to merge child traces)."""
    from agents.base import TraceEvent
    return TraceEvent(
        agent=ev_dict.get("agent", "?"),
        action=ev_dict.get("action", "?"),
        data=ev_dict.get("data", {}),
        reasoning=ev_dict.get("reasoning"),
        video_timestamp=ev_dict.get("video_timestamp"),
        ts_unix=ev_dict.get("ts_unix", time.time()),
    )


def _save_report(report: CouncilReport, audio_path: Path) -> Path:
    out_dir = Path("results/council")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{audio_path.stem}_council.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False, default=str)
    return out_path


# ----- CLI -----
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline_v2 <audio_file> [region=us] [vertical=police] [language=en]")
        sys.exit(1)

    audio = sys.argv[1]
    region = sys.argv[2] if len(sys.argv) > 2 else "us"
    vertical = sys.argv[3] if len(sys.argv) > 3 else "police"
    language = sys.argv[4] if len(sys.argv) > 4 else "en"

    print(f"\n[council] Running on {audio} (region={region}, vertical={vertical})...\n")
    report = run_council(audio, region=region, vertical=vertical, language=language)

    print("\n" + "=" * 70)
    print(f"COUNCIL REPORT — {Path(audio).name}")
    print("=" * 70)
    print(f"Status:           {report.status}")
    print(f"Duration:         {report.duration_sec:.1f}s")
    print(f"Wall clock:       {report.wall_sec:.1f}s")
    if report.error:
        print(f"Error:            {report.error}")

    if report.prosecution:
        v = report.prosecution.get("violations", [])
        print(f"Prosecution:      {len(v)} violations, verdict={report.prosecution.get('verdict')}")
    if report.defense:
        r = report.defense.get("rebuttals", [])
        print(f"Defense:          {len(r)} rebuttals")
    if report.verdict:
        print(f"Judge:            {report.verdict.get('overall_verdict')} (severity={report.verdict.get('overall_severity')})")
        print(f"Headline:         {report.verdict.get('headline')}")

    print(f"\nTrace events:     {len(report.trace)}")
    print(f"Saved to:         results/council/{Path(audio).stem}_council.json")
