"""SENTINEL processing pipeline — reusable from CLI and API."""
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from mistralai.client import Mistral
from speechmatics.batch import (
    AsyncClient,
    JobConfig,
    JobType,
    TranscriptionConfig,
    OperatingPoint,
)

from prompts import get_prompt
from prompts_corporate import PROMPT_CORPORATE_EU

load_dotenv()

MISTRAL_KEY = os.getenv("MISTRAL_API_KEY")
SPEECHMATICS_KEY = os.getenv("SPEECHMATICS_API_KEY")

def get_system_prompt(jurisdiction: str, vertical: str = "police") -> str:
    if vertical == "corporate_security":
        return PROMPT_CORPORATE_EU
    if jurisdiction == "US":
        return PROMPT_US
    elif jurisdiction == "Italy":
        return PROMPT_ITALY
    else:
        return PROMPT_EU

    return PROMPTS_POLICE[jurisdiction]
async def transcribe_audio(audio_path: str, language: str = "en") -> dict:
    config = JobConfig(
        type=JobType.TRANSCRIPTION,
        transcription_config=TranscriptionConfig(
            language=language,
            operating_point=OperatingPoint.ENHANCED,
            diarization="speaker",
        ),
    )
    async with AsyncClient(api_key=SPEECHMATICS_KEY) as client:
        result = await client.transcribe(audio_path, transcription_config=config, timeout=300.0)
        return result.model_dump() if hasattr(result, "model_dump") else dict(result)


def format_transcript(raw_result: dict) -> str:
    lines = []
    results = raw_result.get("results", [])
    current_speaker = None
    current_start = None
    current_words = []

    def flush():
        if current_words and current_start is not None:
            mm = int(current_start) // 60
            ss = int(current_start) % 60
            lines.append(f"[{mm:02d}:{ss:02d}] {current_speaker}: {' '.join(current_words)}")

    for word in results:
        if word.get("type") != "word":
            continue
        alt = word.get("alternatives", [{}])[0]
        spk = alt.get("speaker", "S0")
        content = alt.get("content", "")
        start = word.get("start_time", 0)

        if spk != current_speaker:
            flush()
            current_speaker = spk
            current_start = start
            current_words = [content]
        else:
            current_words.append(content)
    flush()
    return "\n".join(lines)


def extract_events(transcript: str, jurisdiction: str) -> dict:
    client = Mistral(api_key=MISTRAL_KEY)
    system_prompt = get_prompt(jurisdiction)

    response = client.chat.complete(
        model="mistral-medium-latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"TRANSCRIPT:\n\n{transcript}"},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    parsed = json.loads(content)

    # Handle wrapper variations
    if "events" not in parsed and isinstance(parsed.get("violations"), list):
        parsed = {"events": parsed["violations"], "metadata": parsed.get("metadata", {})}
    parsed.setdefault("events", [])
    parsed.setdefault("metadata", {})
    return parsed


def route_events(events: list) -> dict:
    buckets = {
        "misconduct_review": [],
        "officer_defense": [],
        "compliance_archive": [],
        "supervisor_alert": [],
    }
    for e in events:
        route = e.get("routing", "compliance_archive")
        if route in buckets:
            buckets[route].append(e)
        else:
            buckets["compliance_archive"].append(e)
    return buckets


async def run_pipeline(
    audio_path: str,
    jurisdiction: str,
    language: str = "en",
    transcripts_dir: str = "transcripts",
    results_dir: str = "results",
) -> dict:
    """Full pipeline: audio → transcript → events → routed result."""
    audio_path = str(audio_path)
    stem = Path(audio_path).stem
    Path(transcripts_dir).mkdir(exist_ok=True)
    Path(results_dir).mkdir(exist_ok=True)

    # Transcribe
    raw = await transcribe_audio(audio_path, language=language)
    transcript = format_transcript(raw)
    transcript_path = Path(transcripts_dir) / f"{stem}_formatted.txt"
    transcript_path.write_text(transcript, encoding="utf-8")

    # Analyze
    analysis = extract_events(transcript, jurisdiction)
    routing = route_events(analysis["events"])

    result = {
        "audio_file": audio_path,
        "jurisdiction": jurisdiction,
        "language": language,
        "transcript_path": str(transcript_path),
        "metadata": analysis.get("metadata", {}),
        "events": analysis["events"],
        "routing": routing,
    }

    result_path = Path(results_dir) / f"{stem}_{jurisdiction.lower()}.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    result["result_path"] = str(result_path)
    return result