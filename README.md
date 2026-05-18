# SENTINEL — Adversarial AI Court for Police Bodycam

> **Speech → diarized transcript → adversarial legal reasoning → defensible verdict.**
> Four agents argue every case in three jurisdictions. The verdict cites specific
> words spoken at specific seconds — and, when video is available, specific
> moments captured on camera.

🎬 [Demo video](#) · 🌐 [Live demo](#) · 📄 [Slides](#)

![Hero screenshot of /demo page](docs/hero.png)

---

## Why this exists

Tens of millions of police interactions are recorded on bodycams every year
across the US, EU, and Italy. Less than 1% are ever audited. When a complaint
arrives months later, the officer's written report is the de-facto ground truth.

SENTINEL is the audit layer that should have always existed: an adversarial
multi-agent court that processes every recording, cites the exact utterance and
the exact bodycam frame, and produces a defensible verdict in minutes — not
months.

## Bidirectional by design

The Defense agent has equal weight to the Prosecution. On our five demo cases,
the Judge returns `officer_justified` four times — including a case where
narcotics found in the vehicle established probable cause for a search the
Prosecution had flagged as a Fourth Amendment violation. SENTINEL is **not**
anti-police technology. It is the audit layer that protects honest officers
from false complaints and citizens from real misconduct. Both sides need it.
The Judge's reasoning is fully drillable on every ruling.

---

## Architecture

```text
               ┌──────────────────────────────────────────────┐
               │   LAYER 1 — RAPID  (per utterance, <2s)      │
               │   Router → Retrieval → Rapid Prosecution     │
               │   Live alerts surface in UI                  │
               └──────────────────┬───────────────────────────┘
                                  │
                                  ▼  every N utterances OR session end
               ┌──────────────────────────────────────────────┐
               │   LAYER 2 — DEEP COUNCIL                     │
               │     ProsecutionAgent  (gpt-oss-120b)         │
               │              ╲                               │
               │               ◄── VisualContextAgent         │
               │              ╱    (Gemini 3.1 Pro on GCS-    │
               │             ╱      uploaded MP4, once)       │
               │     DefenseAgent     (gemma-3-26B)           │
               └──────────────────┬───────────────────────────┘
                                  │
                                  ▼
               ┌──────────────────────────────────────────────┐
               │   LAYER 3 — VERDICT                          │
               │   JudgeAgent  (Gemini 3.1 Pro)               │
               │   per-rule rulings + reasoning + severity    │
               └──────────────────────────────────────────────┘
```

Every agent writes to a unified `Trace`. Every verdict is fully drillable down
to the exact utterance index and timestamp it cites.

---

## The Speechmatics layer (built around their full stack)

SENTINEL is built around **Speechmatics realtime WebSocket streaming** as its
core capability. Within 500ms of each finalized utterance, the Router Agent
triages it against region-specific case law. Detected violations — by officers
**or** by citizens — trigger live alerts in the UI in under 2 seconds. This is
not post-hoc audit; this is the live compliance layer for the highest-stakes
recorded interactions in society.

```text
┌──────────────────────────────────────────────────────────────────┐
│ TranscriptionAgent — Speechmatics (multi-feature pipeline)       │
│                                                                  │
│ 1. Realtime WebSocket streaming + partials → drives live UI      │
│ 2. Speaker diarization (S1, S2, …) → council sees who said what  │
│ 3. Real-time translation (IT/DE → EN) → EU/Italy jurisdictions   │
│ 4. Sentiment per utterance → fed into Prosecution prompt as      │
│    evidence of tone (aggressive / tense / neutral)               │
│ 5. Topic detection → Router uses topics to pick the rule pack    │
│ 6. Summarization → 2-sentence card in the dashboard              │
└──────────────────────────────────────────────────────────────────┘
```

All six features are wired into `agents/transcription_agent.py` and surface
downstream: `prosecution_agent.py` literally cites `sentiment` per utterance
when building its legal argument.

## The Gemini layer

The **JudgeAgent** runs on **Gemini 3.1 Pro** via Vertex AI. It reads the full
prosecution report, every defense rebuttal, and the visual context — and issues
per-rule rulings with weighted reasoning.

The **VisualContextAgent** also runs on Gemini 3.1 Pro, analyzing the bodycam
MP4 directly (uploaded to GCS, referenced by URI). It returns timestamped key
moments — *"handcuffs visible at t=30s, Miranda read at t=155s, officer lunges
at t=58s"* — which are injected into all three text agents' prompts. **On our
`us_video3` case, Vision is what flipped the verdict from "unclear" to
`officer_at_fault / HIGH`**, with the Judge explicitly citing *"the visual
context confirms the encounter escalated to an actual physical seizure when
the officer lunged at the subject."*

## The Featherless layer

**ProsecutionAgent** runs on `gpt-oss-120b` and **DefenseAgent** on
`gemma-3-26B`, both hosted on Featherless. The dual-provider design is
deliberate: prosecution and defense come from different model families so
neither side dominates. Rapid Layer 1 also runs on Featherless for sub-2s
turnaround.

## The Vultr layer

The entire stack — FastAPI backend, FAISS retrieval indexes, Speechmatics RT
session manager, SSE replay endpoint — runs on **Vultr High Frequency Compute**
with warmup at boot. Cold start is ~8s; subsequent live sessions stream events
at <100ms latency over SSE.

---

## Live demo cases

Run any of these end-to-end with the commands in [Quick start](#quick-start):

| Session | Region | Verdict | Severity | Story |
|---|---|---|---|---|
| `us_aggression` | US | officer_justified | low | Citizen accelerates while officer is partially inside the vehicle — citizen fault, not officer |
| `us_video1` | US | officer_justified | none | Use of force was proportionate to active resistance |
| `us_video2_vision` | US | officer_justified | none | Search & Miranda timing held up under probable cause from discovered narcotics |
| **`us_video3`** | **US** | **officer_at_fault** | **HIGH** | **1A retaliation + unlawful seizure — Vision confirmed officer lunged at filming citizen** |
| `it_domestic` | IT | officer_justified | none | EU jurisdiction — domestic call handled lawfully |

Pre-computed sessions live in `results/live/*_session.json` and stream over SSE.

---

## Quick start

```bash
# 1. Install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys

# 2. Authenticate Google Cloud (for Gemini Judge + Vision)
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID

# 3. Build retrieval indexes (one-time, ~30s)
python -m tools.build_indexes

# 4. Run a full audit on a recording
python pipeline_v2.py recordings/video3_borderline.mp4 us

# 5. Precompute a live session (with Vision)
python -m tools.precompute_live \
    --transcript results/council/video3_borderline_council.json \
    --session-id us_video3 --region us \
    --audio-file recordings/video3_borderline.mp4

# 6. Serve & stream
uvicorn main:app --host 0.0.0.0 --port 8000
curl -N "http://localhost:8000/api/live/replay/us_video3?real_time=true&speed=4.0"
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/audit/upload` | Upload audio/video for batch council |
| POST | `/api/audit/{job_id}/council/run` | Run council on uploaded job |
| GET | `/api/audit/{job_id}` | Job status + full council report |
| GET | `/api/live/sessions` | List precomputed live sessions |
| GET | `/api/live/replay/{session_id}` | SSE stream of session events |

**SSE event kinds:** `session_start`, `utterance`, `rapid_alert`, `deep_scan_started`, `deep_scan_completed`, `visual_context_ready`, `verdict_update`, `final_verdict`, `session_end`.

## Rule packs

Currently supported, each one rule pack JSON away from adding more:

* ✅ **US Police** — 4th/5th/6th Amendment, Graham v. Connor, Miranda v. Arizona, Terry v. Ohio, Illinois v. Wardlow
* ✅ **EU Police** — ECHR Articles 3, 5, 8, EU procedural directives
* ✅ **Italy Police** — Codice di Procedura Penale, Legge 121/1981

Adding a new jurisdiction is one JSON file in `case_law/police_<code>.json` + a rebuild of FAISS indexes (`python -m tools.build_indexes`).

## The engine beyond police

The same adversarial-council architecture powers a `corporate_security` vertical (EU GDPR / labor law) — proof that the design generalizes. Healthcare, insurance, HR, and procurement compliance workflows are downstream. See `prompts_corporate.py`.

## Tech stack

* **Frontend:** Next.js 16, Tailwind v4, shadcn/ui, wavesurfer.js
* **Backend:** FastAPI, SQLModel, SSE-Starlette
* **Speech:** Speechmatics RT + Batch (diarization, translation, sentiment, topics, summary)
* **LLMs:** Featherless (`gpt-oss-120b`, `gemma-3-26B`), Google Gemini 3.1 Pro
* **Retrieval:** FAISS + sentence-transformers over rule-pack JSON
* **Vision:** Gemini 3.1 Pro on GCS-backed video URIs
* **Deploy:** Vultr High Frequency Compute

## Cost per recording

On a 5-10 minute bodycam recording:

* Vision (Gemini 3.1 Pro, single pass): ~$0.05-0.10
* Judge consolidation (Gemini 3.1 Pro): ~$0.02-0.05
* Prosecution + Defense (Featherless): ~$0.01-0.03
* Speechmatics RT+Batch: included in plan

**~$0.10-0.20 per recording.** Cheap enough to audit every interaction.

## License

MIT — see `LICENSE`.

Built at Milan AI Week 2026 Hackathon  
Powered by Speechmatics · Google Gemini · Featherless · Vultr
