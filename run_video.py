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

load_dotenv()

SYSTEM_PROMPT = """You are a legal compliance analyst reviewing police bodycam transcripts.
Identify violations of US constitutional rights and police procedure.

Important context:
- Speaker labels (S1, S2, S3) are anonymous; infer roles from content.
- Consider: Miranda warnings, illegal detention, search consent, denial of counsel, intimidation, excessive force.
- Repeated commands ("Drop the weapon") are NOT violations — they are de-escalation.
- Use of force MAY be justified if subject is armed/non-compliant. Apply Graham v. Connor 1989.

Output STRICT JSON array. Each violation MUST have:
- category: miranda_warning | use_of_force | illegal_search | illegal_detention | denial_of_counsel | intimidation | excessive_force | procedural_violation
- severity: low | medium | high | critical
- timestamp: "MM:SS"
- speaker: S1 | S2 | S3
- quote: exact words from transcript
- regulation: legal reference
- rationale: 2-3 sentences with mitigating context if any

If encounter appears lawful, return []. No false positives.
Return ONLY the JSON array."""


def format_transcript(result) -> str:
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


async def transcribe(audio_path: str) -> str:
    config = JobConfig(
        type=JobType.TRANSCRIPTION,
        transcription_config=TranscriptionConfig(
            language="en",
            operating_point=OperatingPoint.ENHANCED,
            diarization="speaker",
        ),
    )
    async with AsyncClient() as client:
        print(f"📤 Submitting {audio_path}...")
        result = await client.transcribe(audio_path, config=config, timeout=300.0)
        print(f"✅ Transcribed")
        return format_transcript(result)


def extract_violations(transcript: str) -> list:
    client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
    response = client.chat.complete(
        model="mistral-medium-latest",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    parsed = json.loads(response.choices[0].message.content)
    if isinstance(parsed, dict):
        for key in ("violations", "results", "data"):
            if key in parsed:
                return parsed[key]
        return [parsed] if parsed else []
    return parsed


async def main():
    if len(sys.argv) < 2:
        print("Usage: python run_video.py <audio_file>")
        sys.exit(1)

    audio_path = sys.argv[1]
    stem = Path(audio_path).stem

    if not Path(audio_path).exists():
        print(f"❌ Not found: {audio_path}")
        sys.exit(1)

    Path("transcripts").mkdir(exist_ok=True)
    Path("results").mkdir(exist_ok=True)

    # Step 1: transcribe
    transcript = await transcribe(audio_path)
    transcript_file = f"transcripts/{stem}_formatted.txt"
    Path(transcript_file).write_text(transcript, encoding="utf-8")
    print(f"💾 Transcript: {transcript_file}")
    print(f"\n=== TRANSCRIPT (first 400 chars) ===")
    print(transcript[:400])

    # Step 2: extract violations
    print(f"\n🧠 Analyzing with Mistral...")
    violations = extract_violations(transcript)
    violations_file = f"results/{stem}_violations.json"
    Path(violations_file).write_text(
        json.dumps(violations, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n✅ {len(violations)} violation(s) — saved to {violations_file}")
    for i, v in enumerate(violations, 1):
        print(f"\n[{i}] {v.get('category', '?').upper()} — {v.get('severity', '?')}")
        print(f"    [{v.get('timestamp', '?')}] {v.get('speaker', '?')}: \"{v.get('quote', '?')}\"")
        print(f"    {v.get('regulation', '?')}")
        print(f"    → {v.get('rationale', '?')}")


if __name__ == "__main__":
    asyncio.run(main())