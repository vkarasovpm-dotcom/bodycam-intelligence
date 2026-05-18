"""
Precompute a live session from a council JSON transcript.

Runs LivePipeline at full speed (no real-time delays), executes all 3 layers,
and saves the resulting session.json to results/live/<session_id>_session.json.

This is what the SSE replay endpoint will stream back to the frontend.

Usage:
    python -m tools.precompute_live --transcript results/council/1_council.json \\
        --session-id us_aggression --region us

    python -m tools.precompute_live --transcript results/council/italy_domestic_violence_council.json \\
        --session-id it_dv --region it
"""
from __future__ import annotations
import argparse
import asyncio
from pathlib import Path

from pipeline_live import LivePipeline


async def precompute(
    transcript: str,
    session_id: str,
    region: str,
    out_dir: str = "results/live",
    skip_judge: bool = False,
    skip_deep: bool = False,
    audio_file: str | None = None,
) -> Path:
    out_path = Path(out_dir) / f"{session_id}_session.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[precompute] transcript : {transcript}")
    print(f"[precompute] session_id : {session_id}")
    print(f"[precompute] region     : {region}")
    print(f"[precompute] output     : {out_path}")
    print(f"[precompute] skip_judge : {skip_judge}")
    print(f"[precompute] skip_deep  : {skip_deep}")
    print(f"[precompute] audio_file : {audio_file or '(none — audio-only)'}")
    print()

    pipe = LivePipeline(
        session_id=session_id,
        region=region,
        audio_file=audio_file,
    )

    # run_from_replay() already calls finalize() internally when finalize=True (default)
    await pipe.run_from_replay(
        transcript_path=transcript,
        real_time=False,
        speed=1.0,
        finalize=not skip_deep,
    )

    pipe.save(str(out_path))

    stats = pipe.to_dict().get("stats", {})
    print()
    print(f"[precompute] DONE")
    print(f"  utterances        : {stats.get('total_utterances')}")
    print(f"  rapid_alerts      : {stats.get('rapid_alerts')}")
    print(f"  deep_violations   : {stats.get('deep_violations')}")
    print(f"  rebuttals         : {stats.get('rebuttals')}")
    print(f"  verdict_snapshots : {stats.get('verdict_snapshots')}")
    print(f"  saved to          : {out_path}  ({out_path.stat().st_size:,} bytes)")

    return out_path


def main():
    ap = argparse.ArgumentParser(description="Precompute a live session from a transcript.")
    ap.add_argument("--transcript", required=True, help="Path to council JSON transcript.")
    ap.add_argument("--session-id", required=True, help="Session identifier.")
    ap.add_argument("--region", default="us", choices=["us", "eu", "it"])
    ap.add_argument("--out-dir", default="results/live")
    ap.add_argument("--skip-judge", action="store_true", help="Skip final Judge call.")
    ap.add_argument("--skip-deep", action="store_true", help="Skip final deep scan + judge.")
    ap.add_argument("--audio-file", default=None,
                    help="Optional video file (.mp4) for Gemini Vision analysis.")
    args = ap.parse_args()

    asyncio.run(precompute(
        transcript=args.transcript,
        session_id=args.session_id,
        region=args.region,
        out_dir=args.out_dir,
        skip_judge=args.skip_judge,
        skip_deep=args.skip_deep,
        audio_file=args.audio_file,
    ))


if __name__ == "__main__":
    main()
