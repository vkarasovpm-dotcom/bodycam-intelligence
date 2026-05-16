"""End-to-end: existing transcript → Mistral violation extraction."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from mistralai.client import Mistral

load_dotenv()

TRANSCRIPT_FILE = "transcripts/video1_formatted.txt"
OUTPUT_FILE = "results/video1_violations.json"

SYSTEM_PROMPT = """You are a legal compliance analyst reviewing police bodycam transcripts.
Identify violations of US constitutional rights and police procedure.

Important context:
- Speaker labels (S1, S2, S3) are anonymous; infer roles from content.
- Consider proportionality of force, Miranda warnings, illegal detention, search consent, denial of counsel, intimidation.
- Repeated commands ("Drop the knife") are NOT violations — they are de-escalation attempts.
- Use of force MAY be justified if subject is armed and non-compliant. Note this in rationale.

Output STRICT JSON array. Each violation MUST have:
- category: miranda_warning | use_of_force | illegal_search | illegal_detention | denial_of_counsel | intimidation | excessive_force | procedural_violation
- severity: low | medium | high | critical
- timestamp: string like "00:14"
- speaker: S1 | S2 | S3
- quote: exact words from transcript
- regulation: legal reference (e.g., "4th Amendment", "Graham v. Connor 1989", "Miranda v. Arizona 1966")
- rationale: 2-3 sentences explaining WHY this is a violation AND noting any mitigating context

If the encounter appears lawful (e.g., armed suspect, proportional response), return [] with no false positives.
Return ONLY the JSON array."""


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
    raw = response.choices[0].message.content
    parsed = json.loads(raw)
    # Mistral may wrap in {"violations": [...]} or return raw list
    if isinstance(parsed, dict):
        for key in ("violations", "results", "data"):
            if key in parsed:
                return parsed[key]
        return [parsed] if parsed else []
    return parsed


def main():
    Path("results").mkdir(exist_ok=True)

    if not Path(TRANSCRIPT_FILE).exists():
        print(f"❌ Transcript not found: {TRANSCRIPT_FILE}")
        print("Run smoke_speechmatics.py first.")
        return

    transcript = Path(TRANSCRIPT_FILE).read_text(encoding="utf-8")
    print(f"📄 Transcript: {len(transcript)} chars, {transcript.count(chr(10))+1} lines")
    print(f"\n=== TRANSCRIPT PREVIEW (first 500 chars) ===")
    print(transcript[:500])

    print(f"\n🧠 Sending to Mistral...")
    violations = extract_violations(transcript)

    print(f"\n✅ Found {len(violations)} violation(s)")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(violations, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved: {OUTPUT_FILE}")

    print(f"\n=== VIOLATIONS ===")
    for i, v in enumerate(violations, 1):
        print(f"\n[{i}] {v.get('category', '?').upper()} — {v.get('severity', '?')}")
        print(f"    Time: {v.get('timestamp', '?')}  Speaker: {v.get('speaker', '?')}")
        print(f"    Quote: \"{v.get('quote', '?')}\"")
        print(f"    Regulation: {v.get('regulation', '?')}")
        print(f"    Rationale: {v.get('rationale', '?')}")


if __name__ == "__main__":
    main()