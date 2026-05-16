"""Smoke test: Speechmatics batch transcription with diarization."""
import asyncio
import os
import json
import sys
import traceback
from pathlib import Path
from dotenv import load_dotenv

print("🔵 Script started")

load_dotenv()
print(f"🔵 API key present: {bool(os.getenv('SPEECHMATICS_API_KEY'))}")

from speechmatics.batch import (
    AsyncClient,
    JobConfig,
    JobType,
    TranscriptionConfig,
    OperatingPoint,
)
print("🔵 Imports OK")

AUDIO_FILE = "recordings/video1.mp3"
OUTPUT_JSON = "transcripts/video1_raw.json"
OUTPUT_TXT = "transcripts/video1_formatted.txt"


async def transcribe(audio_path: str):
    print("🔵 Building config...")
    config = JobConfig(
        type=JobType.TRANSCRIPTION,
        transcription_config=TranscriptionConfig(
            language="en",
            operating_point=OperatingPoint.ENHANCED,
            diarization="speaker",
            enable_entities=True,
        ),
    )
    print("🔵 Config built. Opening AsyncClient...")

    async with AsyncClient() as client:
        print(f"📤 Submitting {audio_path}... (this can take 30-120 seconds)")
        result = await client.transcribe(
            audio_path,
            config=config,
            timeout=300.0,
        )
        print(f"✅ Transcription returned, type={type(result).__name__}")
        return result


def format_transcript(result) -> str:
    """Build [MM:SS] SPEAKER: text lines from word-level results."""
    # result.results is a list of word/punctuation objects from json-v2
    words = getattr(result, "results", None)
    if not words:
        return "(no word-level results found)"

    lines = []
    current_speaker = None
    current_text = []
    current_start = None

    for w in words:
        # w is a dict-like object from Speechmatics json-v2
        wtype = w.get("type") if isinstance(w, dict) else getattr(w, "type", None)
        if wtype != "word":
            continue

        if isinstance(w, dict):
            alt = w["alternatives"][0]
            speaker = alt.get("speaker", "UNKNOWN")
            content = alt["content"]
            start = w["start_time"]
        else:
            alt = w.alternatives[0]
            speaker = getattr(alt, "speaker", "UNKNOWN")
            content = alt.content
            start = w.start_time

        if speaker != current_speaker:
            if current_text:
                ts = f"{int(current_start // 60):02d}:{int(current_start % 60):02d}"
                lines.append(f"[{ts}] {current_speaker}: {' '.join(current_text)}")
            current_speaker = speaker
            current_text = [content]
            current_start = start
        else:
            current_text.append(content)

    if current_text:
        ts = f"{int(current_start // 60):02d}:{int(current_start % 60):02d}"
        lines.append(f"[{ts}] {current_speaker}: {' '.join(current_text)}")

    return "\n".join(lines)


async def main():
    print("🔵 main() entered")

    if not Path(AUDIO_FILE).exists():
        print(f"❌ Audio file not found: {AUDIO_FILE}")
        return

    print(f"🔵 Audio file size: {Path(AUDIO_FILE).stat().st_size} bytes")
    Path("transcripts").mkdir(exist_ok=True)

    try:
        result = await transcribe(AUDIO_FILE)
    except Exception as e:
        print(f"❌ Exception in transcribe: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    # Inspect result object
    print(f"🔵 Result attributes: {[a for a in dir(result) if not a.startswith('_')][:20]}")

    # Plain transcript
    transcript_text = getattr(result, "transcript_text", None)
    if transcript_text:
        print(f"\n=== PLAIN TRANSCRIPT (first 400 chars) ===")
        print(transcript_text[:400])

    # Save raw JSON (best effort)
    try:
        if hasattr(result, "model_dump"):
            raw = result.model_dump()
        elif hasattr(result, "to_dict"):
            raw = result.to_dict()
        elif hasattr(result, "__dict__"):
            raw = result.__dict__
        else:
            raw = {"transcript_text": transcript_text}
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✅ Raw JSON saved: {OUTPUT_JSON}")
    except Exception as e:
        print(f"⚠ Could not serialize raw result: {e}")

    # Formatted transcript with speakers
    formatted = format_transcript(result)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(formatted)
    print(f"✅ Formatted transcript saved: {OUTPUT_TXT}")
    print(f"\n=== FORMATTED PREVIEW (first 800 chars) ===")
    print(formatted[:800])


if __name__ == "__main__":
    print("🔵 Calling asyncio.run...")
    try:
        asyncio.run(main())
        print("\n🔵 asyncio.run finished")
    except Exception as e:
        print(f"❌ Top-level exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)