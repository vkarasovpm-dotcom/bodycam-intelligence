# SENTINEL

Adversarial AI Court for Police Bodycam

sentinel-audit.co
Milan AI Week 2026

🌐 [Live demo](https://sentinel-audit.co/) · 📄 [Slides](https://storage.googleapis.com/lablab-static-eu/presentations/submissions/octgaogix566cpvjlul7vs5w/octgaogix566cpvjlul7vs5w-1779198324896_msejh8vwzkjwydufthllxv2t.pdf)

## 30-second tour

The fastest way to understand SENTINEL is to watch the adversarial loop in action:

→ **[Open the us_video3 demo](https://sentinel-audit.co/demo/us_video3?autoplay=instant&speed=10)** — a US bodycam case where Prosecution flagged a HIGH-severity Fourth Amendment seizure, Defense rebutted it, and the Judge reduced the verdict to LOW after weighing both arguments.

→ **[Browse all 7 cases](https://sentinel-audit.co/demo)** — four jurisdictions (US / Italy / Netherlands / Spain), all landing on the officer-justified side after adversarial review.

## Why this exists

Tens of millions of police interactions are recorded on bodycams every year across the US, EU, and Italy. Less than 1% are ever audited. When a complaint arrives months later, the officer's written report is the de-facto ground truth.
SENTINEL is the audit layer that should have always existed: an adversarial multi-agent court that processes every recording, cites the exact utterance and the exact bodycam frame, and produces a defensible verdict in minutes — not months.

## Bidirectional by design

The Defense agent has equal weight to the Prosecution. Across our **seven demo cases in four jurisdictions**, every verdict lands on the officer-justified side after adversarial review — six are fully `officer_justified`, and the seventh (`us_video3`) is `mixed / LOW` after the Defense dismissed a Prosecution claim that had been flagged HIGH. This includes a US case where narcotics found in the vehicle established probable cause for a search the Prosecution had flagged as a Fourth Amendment violation, and a Dutch tactical entry where Vision evidence justified the use of force. SENTINEL is **not** anti-police technology. It is the audit layer that protects honest officers from false complaints and citizens from real misconduct. Both sides need it. The Judge's reasoning is fully drillable on every ruling.

## Architecture

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

Every agent writes to a unified `Trace`. Every verdict is fully drillable down to the exact utterance index and timestamp it cites.

## What makes a verdict defensible

Every ruling SENTINEL produces is drillable to the source:
- **Verdict** → cites specific **rule IDs** (e.g. `US-4A-SEIZURE`, `US-1A-RECORD-POLICE`)
- **Rule ID** → cites the **Judge's reasoning paragraph**
- **Reasoning** → cites specific **utterance indices** with **timestamps** (e.g. utterance #15 at t=15s)
- **Utterance** → links to the **diarized transcript** (S1 said exactly this at this second)
- **When video is available** → also cites **VisualContextAgent frames** with timestamps

No black box. Every claim sourced to the recording. Reproducible. Discoverable in court.

## The Speechmatics layer (built around their full stack)

SENTINEL is built around `Speechmatics realtime WebSocket streaming` as its core capability. Within 500ms of each finalized utterance, the Router Agent triages it against region-specific case law. Detected violations — by officers `or` by citizens — trigger live alerts in the UI in under 2 seconds. This is not post-hoc audit; this is the live compliance layer for the highest-stakes recorded interactions in society.

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

All six features are wired into `agents/transcription_agent.py` and surface downstream: `prosecution_agent.py` literally cites `sentiment` per utterance when building its legal argument.

## The Gemini layer

The `JudgeAgent` runs on `Gemini 3.1 Pro` via Vertex AI. It reads the full prosecution report, every defense rebuttal, and the visual context — and issues per-rule rulings with weighted reasoning.

The **VisualContextAgent** also runs on Gemini 3.1 Pro, analyzing the bodycam MP4 directly (uploaded to GCS, referenced by URI). It returns timestamped key moments — "handcuffs visible at t=30s, Miranda read at t=155s, officer turns away at t=58s" — which are injected into all three text agents' prompts. The Judge can cite specific visual evidence alongside specific utterances when issuing per-rule rulings, making every verdict defensible to a lawyer at the level of "at this exact second, the officer did this exact thing."

## The Featherless layer

`ProsecutionAgent` runs on `gpt-oss-120b` and `DefenseAgent` on `gemma-3-26B`, both hosted on Featherless. The dual-provider design is deliberate: prosecution and defense come from different model families so neither side dominates. Rapid Layer 1 also runs on Featherless for sub-2s turnaround.

## The Vultr layer

The entire stack — FastAPI backend, FAISS retrieval indexes, Speechmatics RT session manager, SSE replay endpoint — runs on `Vultr High Frequency Compute` with warmup at boot. Cold start is ~8s; subsequent live sessions stream events at <100ms latency over SSE.

## Live demo cases

| Session | Region | Verdict | Severity | Story |
|---|---|---|---|---|
| **`us_video3`** | **US** | **mixed** | **LOW** | **Citizen filming in public park — Prosecution flagged HIGH 4A seizure, Defense rebutted, Judge reduced to LOW** |
| `us_aggression` | US | officer_justified | none | Suspect flees vape shop; Pennsylvania v. Mimms and fleeing-suspect doctrine dismiss all charges |
| `us_video1` | US | officer_justified | none | Sudden knife encounter — less-lethal force proportionate under Graham v. Connor |
| `us_video2_vision` | US | officer_justified | none | Warrantless search vindicated after vehicle console reveals hidden narcotics |
| `it_carabinieri_arrest` | IT | mixed | medium | Night apprehension under Codice di Procedura Penale and de-escalation protocols |
| `nl_politie_inval` | NL | officer_justified | none | Tactical room-clearing entry — Vision extracts hidden handgun threat, ECHR life protections held |
| `es_robbery_shootout` | ES | officer_justified | none | Armed robbery tactical engagement — adversarial review filters 23 noisy alerts to zero violations under ECHR proportionality |

Pre-computed sessions live in `results/live/*_session.json` and stream over SSE.

> **Note on recordings:** The MP4 files in `recordings/` are not committed (privacy + size). The pre-computed `results/live/*_session.json` files are enough to replay any demo via the SSE endpoint. To run a fresh audit, supply your own bodycam recording.

## Quick start

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

## API endpoints

| Method | Path | Description |
|---|---|---|
| POST | /api/audit/upload | Upload audio/video for batch council |
| POST | /api/audit/{job_id}/council/run | Run council on uploaded job |
| GET | /api/audit/{job_id} | Job status + full council report |
| GET | /api/live/sessions | List precomputed live sessions |
| GET | /api/live/replay/{session_id} | SSE stream of session events |

SSE event kinds: `session_start`, `utterance`, `rapid_alert`, `deep_scan_started`, `deep_scan_completed`, `visual_context_ready`, `verdict_update`, `final_verdict`, `session_end`.

## Rule packs

✅ **US Police** — 4th/5th/6th Amendment, Graham v. Connor, Miranda v. Arizona, Terry v. Ohio, Illinois v. Wardlow, Pennsylvania v. Mimms
✅ **EU Police** — ECHR Articles 2, 3, 5, 8; EU procedural directives (used for NL Politie, ES Policía Nacional, and other EU jurisdictions)
✅ **Italy Police** — Codice di Procedura Penale, Legge 121/1981 (Carabinieri-specific)

Adding a new jurisdiction is one JSON file in `case_law/police_<code>.json` + a rebuild of FAISS indexes (python -m tools.build_indexes).

## Designed for regulated deployment

- **Data residency** — runs entirely on Vultr EU regions. No data leaves the customer's tenancy.
- **Human in the loop** — SENTINEL produces verdicts, not decisions. Every ruling is a recommendation for an oversight officer to sign off on.
- **Full auditability** — every agent writes to a unified `Trace`. Reproducible. Discoverable in court.
- **Bias by construction** — Defense and Prosecution run on different model families (gemma vs gpt-oss) so neither side dominates the reasoning.

## The engine beyond police

The same adversarial-council architecture powers a `corporate_security` vertical (EU GDPR / labor law) — proof that the design generalizes. Healthcare, insurance, HR, and procurement compliance workflows are downstream. See `prompts_corporate.py`.

## Tech stack

Frontend: Next.js 16, Tailwind v4, shadcn/ui, wavesurfer.js
Backend: FastAPI, SQLModel, SSE-Starlette
Speech: Speechmatics RT + Batch (diarization, translation, sentiment, topics, summary)
LLMs: Featherless (gpt-oss-120b, gemma-3-26B), Google Gemini 3.1 Pro
Retrieval: FAISS + sentence-transformers over rule-pack JSON
Vision: Gemini 3.1 Pro on GCS-backed video URIs
Deploy: Vultr High Frequency Compute

## Cost per recording

On a 5-10 minute bodycam recording:
- Vision (Gemini 3.1 Pro, single pass): ~$0.05-0.10
- Judge consolidation (Gemini 3.1 Pro): ~$0.02-0.05
- Prosecution + Defense (Featherless): ~$0.01-0.03
- Speechmatics RT+Batch: included in plan

~$0.10-0.20 per recording. Cheap enough to audit every interaction.

## License

[MIT License](https://github.com/vkarasovpm-dotcom/bodycam-intelligence?tab=MIT-1-ov-file) — see `LICENSE` tab for details.

Built at Milan AI Week 2026 Hackathon
Powered by Vultr · Google Gemini · Featherless · Speechmatics
