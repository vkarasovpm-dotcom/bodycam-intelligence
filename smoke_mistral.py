import os
import json
from dotenv import load_dotenv
from mistralai.client import Mistral

load_dotenv()

client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

TEST_TRANSCRIPT = """
[00:03] OFFICER_1: Step out of the vehicle now!
[00:05] CIVILIAN: Why are you pulling me over, officer?
[00:07] OFFICER_1: I said get out before I drag you out.
[00:12] CIVILIAN: Am I being detained? Am I free to go?
[00:14] OFFICER_1: Shut your mouth. Hands behind your back.
[00:18] CIVILIAN: I want to speak to a lawyer.
[00:20] OFFICER_1: You'll talk when I tell you to talk.
[00:25] OFFICER_2: We're searching your car now.
[00:27] CIVILIAN: I don't consent to any searches.
[00:29] OFFICER_2: We don't need your consent. Move.
"""

SYSTEM_PROMPT = """You are a legal compliance analyst reviewing police bodycam transcripts.
Identify violations of US constitutional rights and police procedure.

Output STRICT JSON array. Each violation object MUST have:
- category: one of [miranda_warning, use_of_force, illegal_search, illegal_detention, denial_of_counsel, intimidation, refusal_to_identify_reason]
- severity: one of [low, medium, high, critical]
- timestamp: string like "00:14"
- speaker: officer_1 | officer_2 | civilian
- quote: exact words from transcript
- regulation: legal article (e.g., "4th Amendment", "Miranda v. Arizona 1966")
- rationale: 1-2 sentence explanation

Return ONLY the JSON array, no preamble."""

response = client.chat.complete(
    model="mistral-medium-latest",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Transcript:\n{TEST_TRANSCRIPT}"},
    ],
    response_format={"type": "json_object"},
    temperature=0.1,
)

raw = response.choices[0].message.content
print("=== RAW RESPONSE ===")
print(raw)
print("\n=== PARSED ===")
violations = json.loads(raw)
print(json.dumps(violations, indent=2, ensure_ascii=False))
print(f"\n✅ Found {len(violations.get('violations', violations)) if isinstance(violations, dict) else len(violations)} violations")