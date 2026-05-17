"""SENTINEL — Bidirectional, multi-jurisdiction bodycam analysis pipeline.

Usage:
    python run_video.py recordings/video1.mp3 --jurisdiction US
    python run_video.py recordings/italian_carabinieri.mp3 --jurisdiction Italy
    python run_video.py recordings/eu_video.mp3 --jurisdiction EU
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()

from speechmatics.batch import (
    AsyncClient,
    JobConfig,
    JobType,
    TranscriptionConfig,
    OperatingPoint,
)
from mistralai.client import Mistral

from prompts import get_prompt
from prompts_corporate import PROMPT_CORPORATE_EU

load_dotenv()


# ============ TRANSCRIPTION ============

def format_transcript(result) -> str:
    """Build [MM:SS] SPEAKER: text lines from word-level results."""
    words = getattr(result, "results", None) or []
    lines = []
    current_speaker = None
    current_text = []
    current_start = None

    for w in words:
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


async def transcribe(audio_path: str, language: str = "en") -> tuple[str, dict]:
    """Returns (formatted_transcript, raw_metadata)."""
    config = JobConfig(
        type=JobType.TRANSCRIPTION,
        transcription_config=TranscriptionConfig(
            language=language,
            operating_point=OperatingPoint.ENHANCED,
            diarization="speaker",
        ),
    )
    async with AsyncClient() as client:
        print(f"📤 Submitting {audio_path} (lang={language})...")
        result = await client.transcribe(audio_path, config=config, timeout=300.0)
        print(f"✅ Transcribed")

    transcript = format_transcript(result)
    metadata = {
        "duration_sec": getattr(result.metadata, "duration", None) if hasattr(result, "metadata") else None,
        "speaker_count": len(getattr(result, "speakers", []) or []),
        "language": language,
    }
    return transcript, metadata


# ============ ANALYSIS ============

def extract_events(transcript: str, jurisdiction: str, vertical: str = "police") -> list:
    """Run Mistral with jurisdiction- and vertical-specific prompt."""
    client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
    if vertical == "corporate_security":
        system_prompt = PROMPT_CORPORATE_EU
    else:
        system_prompt = get_prompt(jurisdiction)


    response = client.chat.complete(
        model="mistral-medium-latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    parsed = json.loads(raw)

    # Expect {"events": [...]} but handle variations
    if isinstance(parsed, dict):
        for key in ("events", "violations", "results", "incidents"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        # If dict but no known key, treat values as events if list
        for v in parsed.values():
            if isinstance(v, list):
                return v
        return []
    if isinstance(parsed, list):
        return parsed
    return []


# ============ ROUTING ============

ROUTING_ALIASES = {
    # corporate → police canonical channels (same semantics)
    "hr_review": "misconduct_review",
    "security_incident": "supervisor_alert",
    "guard_defense": "officer_defense",
}

def route_events(events: list) -> dict:
    """Group events by routing destination (corporate labels mapped to canonical)."""
    routed = {
        "misconduct_review": [],
        "officer_defense": [],
        "compliance_archive": [],
        "supervisor_alert": [],
    }
    for ev in events:
        target = ev.get("routing", "compliance_archive")
        target = ROUTING_ALIASES.get(target, target)
        if target not in routed:
            target = "compliance_archive"
        routed[target].append(ev)
    return routed

# ============ REPORT ============

ICONS = {
    "officer_to_citizen": "🔴",
    "citizen_to_officer": "🛡",
    "neutral": "🟢",
}

ROUTING_LABELS = {
    "misconduct_review": "→ Misconduct Review Queue (IA / IPCAN / Garante)",
    "officer_defense": "→ Officer Defense File (Police Union / Supervisor)",
    "compliance_archive": "→ Compliance Archive",
    "supervisor_alert": "🚨 SUPERVISOR ALERT — IMMEDIATE",
}


def print_report(events: list, jurisdiction: str, metadata: dict):
    print(f"\n{'='*70}")
    print(f"SENTINEL REPORT — Jurisdiction: {jurisdiction}")
    print(f"{'='*70}")

    if metadata.get("duration_sec"):
        print(f"Duration: {metadata['duration_sec']:.1f}s  |  Speakers detected: {metadata.get('speaker_count', '?')}")
    print(f"Total events: {len(events)}")

    if not events:
        print("\n✅ No incidents detected. Interaction appears compliant.")
        return

    # Group by direction
    by_dir = {"officer_to_citizen": [], "citizen_to_officer": [], "neutral": []}
    for ev in events:
        by_dir.setdefault(ev.get("direction", "neutral"), []).append(ev)

    for direction, label in [
        ("officer_to_citizen", "OFFICER-SIDE VIOLATIONS"),
        ("citizen_to_officer", "CITIZEN-SIDE INCIDENTS"),
        ("neutral", "NEUTRAL / LAWFUL CONTEXT"),
    ]:
        if not by_dir.get(direction):
            continue
        print(f"\n{ICONS[direction]} {label} ({len(by_dir[direction])})")
        print("-" * 70)
        for ev in by_dir[direction]:
            conf = ev.get("confidence", 0)
            conf_str = f"{conf*100:.0f}%" if isinstance(conf, (int, float)) else "?"
            print(f"  [{ev.get('timestamp','?')}] {ev.get('category','?').upper()} ({ev.get('severity','?')}) — confidence {conf_str}")
            print(f"  Speaker {ev.get('speaker','?')}: \"{ev.get('quote','?')[:120]}\"")
            print(f"  Regulation: {ev.get('regulation','?')}")
            print(f"  Rationale:  {ev.get('rationale','?')}")
            print(f"  {ROUTING_LABELS.get(ev.get('routing','compliance_archive'), ev.get('routing','?'))}")
            print()

    # Routing summary
    routed = route_events(events)
    print(f"\n📬 SIGNAL DISPATCH SUMMARY")
    print("-" * 70)
    for channel, items in routed.items():
        if items:
            print(f"  {ROUTING_LABELS.get(channel, channel)}: {len(items)} event(s)")


# ============ MAIN ============

async def main():
    parser = argparse.ArgumentParser(description="SENTINEL bodycam analyzer")
    parser.add_argument("audio_file", help="Path to audio/video file")
    parser.add_argument("--jurisdiction", "-j", default="US", choices=["US", "EU", "Italy"],
                        help="Legal jurisdiction (default: US)")
    parser.add_argument("--language", "-l", default="en", help="Audio language (default: en)")
    parser.add_argument("--vertical", "-v", default="police",
                        choices=["police", "corporate_security"],
                        help="Vertical (default: police)")
    parser.add_argument("--skip-transcribe", action="store_true",
                        help="Reuse existing transcript file instead of calling Speechmatics")
    args = parser.parse_args()

    audio_path = Path(args.audio_file)
    if not audio_path.exists():
        print(f"❌ Not found: {audio_path}")
        sys.exit(1)

    Path("transcripts").mkdir(exist_ok=True)
    Path("results").mkdir(exist_ok=True)

    stem = audio_path.stem
    transcript_file = Path(f"transcripts/{stem}_formatted.txt")

    if args.skip_transcribe and transcript_file.exists():
        print(f"♻️  Reusing existing transcript: {transcript_file}")
        transcript = transcript_file.read_text(encoding="utf-8")
        metadata = {"duration_sec": None, "speaker_count": None}
    else:
        transcript, metadata = await transcribe(str(audio_path), language=args.language)
        transcript_file.write_text(transcript, encoding="utf-8")
        print(f"💾 Transcript saved: {transcript_file}")

    print(f"\n📄 Transcript preview (first 300 chars):")
    print(transcript[:300])

    print(f"\n🧠 Analyzing under jurisdiction: {args.jurisdiction}, vertical: {args.vertical}...")
    events = extract_events(transcript, args.jurisdiction, args.vertical)

    results_file = Path(f"results/{stem}_{args.jurisdiction.lower()}.json")
    output = {
        "audio_file": str(audio_path),
        "jurisdiction": args.jurisdiction,
        "vertical": args.vertical,
        "language": args.language,
        "metadata": metadata,
        "events": events,
        "routing": route_events(events),
    }
    results_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print_report(events, args.jurisdiction, metadata)
    print(f"\n💾 Full JSON saved: {results_file}")

    suffix = "_corp" if args.vertical == "corporate_security" else ""
    results_file = Path(f"results/{stem}_{args.jurisdiction.lower()}{suffix}.json")

if __name__ == "__main__":
    asyncio.run(main())