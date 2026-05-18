"""SENTINEL Replay Transcription Agent.

Reads a finalized batch transcript JSON (produced by transcription_agent.py)
and yields utterances as if they were arriving live. Two modes:

  - real_time=True  : sleep between utterances proportional to their gap
                      in the original recording (for /api/live/replay SSE).
  - real_time=False : yield immediately (for offline precompute).

Each yielded Utterance carries:
    text, speaker, t_start, t_end, utt_index
"""
from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

log = logging.getLogger("sentinel.agent")


@dataclass
class Utterance:
    text: str
    speaker: str
    t_start: float
    t_end: float
    utt_index: int

    @property
    def duration(self) -> float:
        return max(0.0, self.t_end - self.t_start)


def _extract_utterances(raw: dict) -> list[Utterance]:
    """Parse the various transcript-JSON shapes we have on disk.

    Supported shapes (tried in order):
      A0. results/council/<id>_council.json  → raw["transcription"]["utterances"]
      A1. top-level "utterances" : pre-grouped {speaker,text,start,end}
      B.  Speechmatics raw "results" word-level objects
    """
    # Shape A0: full council JSON — utterances nested under "transcription"
    tr = raw.get("transcription")
    if isinstance(tr, dict) and isinstance(tr.get("utterances"), list) and tr["utterances"]:
        raw = tr  # fall through into Shape A1 with the inner dict

    # Shape A1: pre-grouped utterances (our preferred format)
    if isinstance(raw.get("utterances"), list) and raw["utterances"]:
        out = []
        for i, u in enumerate(raw["utterances"]):
            text = (u.get("text") or u.get("transcript") or "").strip()
            if not text:
                continue
            out.append(Utterance(
                text=text,
                speaker=str(u.get("speaker", "S1")),
                t_start=float(u.get("start", u.get("t_start", 0.0))),
                t_end=float(u.get("end", u.get("t_end", 0.0))),
                utt_index=i,
            ))
        # Some batch pipelines emit one "utterance" per word/word-pair.
        # Merge micro-fragments back into sentence-level utterances so router
        # has enough context to classify properly.
        return _merge_micro_utterances(out)

    # Shape B: Speechmatics word-level "results"
    results = raw.get("results") or []
    if results:
        groups: list[Utterance] = []
        cur_words: list[str] = []
        cur_speaker: Optional[str] = None
        cur_start: float = 0.0
        cur_end: float = 0.0
        last_end: float = 0.0
        SILENCE_BREAK = 0.8  # seconds of silence → new utterance

        def flush():
            nonlocal cur_words, cur_speaker, cur_start, cur_end
            if cur_words:
                groups.append(Utterance(
                    text=" ".join(cur_words).strip(),
                    speaker=cur_speaker or "S1",
                    t_start=cur_start,
                    t_end=cur_end,
                    utt_index=len(groups),
                ))
            cur_words = []
            cur_speaker = None
            cur_start = 0.0
            cur_end = 0.0

        for w in results:
            if w.get("type") and w["type"] != "word":
                continue
            alts = w.get("alternatives") or []
            if not alts:
                continue
            content = (alts[0].get("content") or "").strip()
            if not content:
                continue
            spk = str(alts[0].get("speaker", "S1"))
            t0 = float(w.get("start_time", 0.0))
            t1 = float(w.get("end_time", t0))

            new_speaker = cur_speaker is not None and spk != cur_speaker
            big_gap = (t0 - last_end) > SILENCE_BREAK
            sentence_end = cur_words and cur_words[-1].endswith((".", "!", "?"))

            if new_speaker or big_gap or sentence_end:
                flush()

            if not cur_words:
                cur_start = t0
                cur_speaker = spk
            cur_words.append(content)
            cur_end = t1
            last_end = t1

        flush()
        return groups

    return []




def _merge_micro_utterances(
    utts: list[Utterance],
    silence_break_sec: float = 1.0,
    max_words: int = 30,
    max_duration_sec: float = 8.0,
) -> list[Utterance]:
    """Coalesce word/phrase fragments into sentence-level utterances.

    Triggers a flush when ANY of:
      - speaker changes
      - silence gap exceeds silence_break_sec
      - accumulated word count exceeds max_words
      - accumulated duration exceeds max_duration_sec
      - previous fragment ends with sentence-final punctuation (. ! ?)
    """
    if not utts:
        return []

    merged: list[Utterance] = []
    cur_parts: list[str] = []
    cur_speaker: Optional[str] = None
    cur_start: float = 0.0
    cur_end: float = 0.0

    def flush():
        nonlocal cur_parts, cur_speaker, cur_start, cur_end
        if not cur_parts:
            return
        text = " ".join(cur_parts).strip()
        # Tidy: collapse spaces before punctuation, collapse double spaces
        import re as _re
        text = _re.sub(r"\s+([.,!?;:])", r"\1", text)
        text = _re.sub(r"\s+", " ", text).strip()
        if text:
            merged.append(Utterance(
                text=text,
                speaker=cur_speaker or "S1",
                t_start=cur_start,
                t_end=cur_end,
                utt_index=len(merged),
            ))
        cur_parts = []
        cur_speaker = None
        cur_start = 0.0
        cur_end = 0.0

    for u in utts:
        speaker_changed = cur_speaker is not None and u.speaker != cur_speaker
        gap = u.t_start - cur_end if cur_parts else 0.0
        big_gap = gap > silence_break_sec
        too_long_words = sum(len(p.split()) for p in cur_parts) >= max_words
        too_long_time = cur_parts and (u.t_end - cur_start) > max_duration_sec

        # NOTE: we intentionally do NOT split on sentence-final punctuation.
        # Short exclamations like "Hey! Stop! Stop!" carry meaning only when
        # grouped together, and a single "Stop!" gives router zero legal signal.
        if speaker_changed or big_gap or too_long_words or too_long_time:
            flush()

        if not cur_parts:
            cur_speaker = u.speaker
            cur_start = u.t_start
        cur_parts.append(u.text)
        cur_end = u.t_end

    flush()
    return merged


class ReplayTranscriptionAgent:
    """Yields utterances from a pre-existing transcript file."""

    def __init__(self, transcript_path: str | Path):
        self.transcript_path = Path(transcript_path)
        if not self.transcript_path.exists():
            raise FileNotFoundError(f"Transcript not found: {self.transcript_path}")
        raw = json.loads(self.transcript_path.read_text(encoding="utf-8"))
        self.utterances: list[Utterance] = _extract_utterances(raw)
        log.info(
            f"[replay_transcription] loaded {len(self.utterances)} utterances "
            f"from {self.transcript_path.name}"
        )

    async def stream(self, real_time: bool = True,
                     speed: float = 1.0,
                     max_gap: float = 3.0) -> AsyncIterator[Utterance]:
        """Yield utterances.

        Args:
            real_time: sleep between utterances using original timing.
            speed:     >1.0 plays back faster (e.g. 2.0 = 2x speed).
            max_gap:   cap sleep at this many seconds (so a 30-second pause
                       doesn't freeze the demo).
        """
        prev_end = 0.0
        for u in self.utterances:
            if real_time:
                gap = max(0.0, u.t_start - prev_end)
                gap = min(gap, max_gap) / max(speed, 0.01)
                if gap > 0.0:
                    await asyncio.sleep(gap)
            yield u
            prev_end = u.t_end


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", help="Path to transcript JSON")
    parser.add_argument("--real-time", action="store_true")
    parser.add_argument("--speed", type=float, default=4.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def main():
        agent = ReplayTranscriptionAgent(args.transcript)
        async for u in agent.stream(real_time=args.real_time, speed=args.speed):
            print(f"  [t={u.t_start:6.2f}s {u.speaker}] {u.text}")

    asyncio.run(main())
