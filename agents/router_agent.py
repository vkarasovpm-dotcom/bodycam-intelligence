"""SENTINEL Router Agent — fast triage of live utterances.

Stage 1 (keyword pre-filter): instant, local — kills 60-70% of utterances as 'none'
Stage 2 (LLM): Featherless gemma-4-E4B-it, ~300-800ms — only on potentially interesting

Classifications:
  - none              : no rule trigger
  - officer_violation : officer may have violated a rule (Miranda, force, search)
  - citizen_violation : citizen crime (threats, assault, resisting, fleeing)
  - escalation        : tension rising, commands being issued
  - de_escalation     : positive action by officer

Also produces a `query_rewrite` for retrieval — converts colloquial utterance
into legally-targeted query so retrieval lands on correct rules.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from agents.base import Trace, featherless_client, MODELS


# ---------------------------------------------------------------------------
# Keyword banks (fast, local)
# ---------------------------------------------------------------------------

OFFICER_VIOLATION_KEYWORDS = {
    "under arrest", "you're arrested", "you are arrested", "you are under arrest",
    "in custody", "cuff him", "cuff her", "put your hands behind",
    "tase", "taser", "shoot", "fire", "drew his weapon", "drew her weapon", "gun out",
    "strike", "hit him", "hit her", "punch", "knee on",
    "search the", "pat down", "frisk", "empty your pockets", "step out of the car",
    "i'll jail you", "going to jail", "get on the ground", "get down now",
    "shut up", "shut the fuck up", "tell us where", "we'll hurt you",
}

OFFICER_DEESCALATION_KEYWORDS = {
    "calm down", "please calm", "let's talk", "i hear you", "i understand",
    "take a breath", "sir, please", "ma'am, please", "no one is hurting you",
    "you have the right to remain silent",
    "you have the right to an attorney",
    "you are not under arrest", "you're free to go", "free to leave",
}

CITIZEN_VIOLATION_KEYWORDS = {
    "i'll kill", "i will kill", "kill you", "kill your", "i'll fucking kill",
    "i'll shoot", "i'll cut", "i'll stab", "burn you", "find your family",
    "you're dead", "you are dead",
    "spit on", "spits on",
    "ti ammazzo", "ammazzo",
    "i'm not going", "i won't", "get off me", "let me go", "don't touch me",
    "fuck off",
}

ESCALATION_KEYWORDS = {
    "stop resisting", "stop fighting", "back up", "drop it", "drop the",
    "put it down", "show me your hands", "hands up", "hands where i can see",
    "i said stop", "last warning", "final warning", "stop the vehicle",
}

TRIVIAL_PATTERNS = [
    re.compile(r"^\s*(yes|no|ok|okay|yeah|nope|uh|um|hm|hmm|right)\s*[.!?]?\s*$", re.I),
    re.compile(r"^\s*(thank you|thanks|please|sorry)\s*[.!?]?\s*$", re.I),
]

VALID_CLASSES = {"none", "officer_violation", "citizen_violation", "escalation", "de_escalation"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RouterClassification:
    classification: str
    confidence: float
    query_rewrite: str = ""        # legally-targeted query for retrieval
    matched_keywords: list[str] = field(default_factory=list)
    stage: str = "keyword"          # keyword | llm | trivial
    latency_ms: float = 0.0
    raw_llm_response: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

ROUTER_SYSTEM_PROMPT = """You are a real-time legal triage classifier for police bodycam audio.

Classify the CURRENT utterance into ONE of:
- none              : no rule trigger, routine speech
- officer_violation : officer may have violated constitutional rights or use-of-force rules
- citizen_violation : citizen committed a crime (threats, assault on officer, resisting, fleeing)
- escalation        : tension rising, commands issued, but no clear violation yet
- de_escalation     : officer calming, advising rights properly, attempting non-force resolution

Rules:
- Profanity from a citizen ALONE is protected speech, NOT citizen_violation.
- Proper Miranda warning is de_escalation.
- An officer giving a lawful command with cause is "escalation" or "none", not "officer_violation".

CRITICAL DISTINCTIONS (override the above when these apply):
- "You're under arrest" / "in custody" WITHOUT a prior Miranda warning in context
  → officer_violation (Miranda v. Arizona, 5th Amendment).
- Force, shouting, or commands directed at a HANDCUFFED / RESTRAINED / COMPLIANT subject
  → officer_violation (ECHR Art. 3 Bouyid; 4th Amendment Graham v. Connor).
- Threats of harm by an officer during questioning ("we'll hurt you", "tell us or else")
  → officer_violation (coerced confession; ECHR Art. 3 Gäfgen).
- Search without consent/warrant/probable cause stated → officer_violation (4th Amendment).
- "Show me your hands! Last warning!" at an ARMED or ACTIVELY THREATENING subject
  → escalation (lawful command, no violation yet).

escalation = tension rising, no specific legal duty breached yet.
officer_violation = a specific legal duty has ALREADY been breached in this utterance.

ALSO produce a SHORT (8-15 words) legally-targeted query rewrite that describes
the LEGAL situation, not the literal words. This query feeds a semantic search
over case law. Examples:
  - Utterance "you're under arrest get in the car"
    → "officer announces arrest without prior Miranda warning"
  - Utterance "il sospettato si è opposto fisicamente all'arresto"
    → "citizen physically resisting lawful arrest"
  - Utterance "we'll hurt you bad if you don't tell us"
    → "officer threatens harm during interrogation to coerce statement"
  - Utterance "Sir, please calm down."
    → "officer attempting verbal de-escalation"

Respond with STRICT JSON only, no preamble:
{"classification": "<label>", "confidence": <0.0-1.0>, "query_rewrite": "<8-15 words>"}
"""


# ---------------------------------------------------------------------------
# RouterAgent
# ---------------------------------------------------------------------------

class RouterAgent:
    def __init__(self, region: str = "us", vertical: str = "police", trace: Optional[Trace] = None):
        self.region = region.lower()
        self.vertical = vertical.lower()
        self.trace = trace or Trace()
        self.model = MODELS["router"]
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = featherless_client()
        return self._client

    # ---- Stage 1: keyword ----
    @staticmethod
    def _match(text: str, bank: set[str]) -> list[str]:
        low = text.lower()
        return [kw for kw in bank if kw in low]

    def _keyword_classify(self, utterance: str) -> Optional[RouterClassification]:
        text = utterance.strip()
        if len(text) < 6:
            return RouterClassification(classification="none", confidence=0.95, stage="trivial",
                                        query_rewrite="")
        for pat in TRIVIAL_PATTERNS:
            if pat.match(text):
                return RouterClassification(classification="none", confidence=0.95, stage="trivial",
                                            query_rewrite="")

        cit = self._match(text, CITIZEN_VIOLATION_KEYWORDS)
        off = self._match(text, OFFICER_VIOLATION_KEYWORDS)
        deesc = self._match(text, OFFICER_DEESCALATION_KEYWORDS)
        esc = self._match(text, ESCALATION_KEYWORDS)

        # Strong de-escalation, no other → fast positive flag
        if deesc and not off and not cit:
            return RouterClassification(
                classification="de_escalation", confidence=0.80,
                matched_keywords=deesc, stage="keyword",
                query_rewrite="officer attempting verbal de-escalation or advising rights",
            )

        hit_count = sum(1 for h in [cit, off, deesc, esc] if h)
        if hit_count == 0:
            # Short non-trivial → likely none
            if len(text.split()) <= 4:
                return RouterClassification(classification="none", confidence=0.75, stage="keyword",
                                            query_rewrite="")
            # Otherwise escalate to LLM
            return None

        # Multi-bank hit → ambiguous → LLM
        if hit_count > 1:
            return None

        # Single bank hit → keep heuristic, but escalate to LLM for query_rewrite
        # (keyword stage cannot produce a good legal query rewrite reliably)
        return None  # let LLM handle nuance + query_rewrite

    # ---- Stage 2: LLM ----
    def _llm_classify(self, utterance: str, context: list[str]) -> RouterClassification:
        prior = "\n".join(f"- {c}" for c in context[-5:]) if context else "(no prior context)"
        user_prompt = (
            f"PRIOR CONTEXT (up to 5 utterances):\n{prior}\n\n"
            f"CURRENT UTTERANCE:\n\"{utterance}\"\n\n"
            f"Classify and produce a query rewrite. STRICT JSON only."
        )

        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=120,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            return RouterClassification(
                classification="none", confidence=0.40, stage="llm",
                query_rewrite="",
                raw_llm_response=f"ERROR: {type(e).__name__}: {str(e)[:160]}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        latency_ms = (time.perf_counter() - t0) * 1000

        # Parse JSON (lenient)
        clean = raw.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)

        label = "none"
        conf = 0.5
        rewrite = ""
        try:
            parsed = json.loads(clean)
            label = str(parsed.get("classification", "none")).lower().strip()
            conf = float(parsed.get("confidence", 0.5))
            rewrite = str(parsed.get("query_rewrite", "")).strip()
        except Exception:
            m = re.search(r'"classification"\s*:\s*"([^"]+)"', clean)
            if m:
                label = m.group(1).lower().strip()
            m = re.search(r'"query_rewrite"\s*:\s*"([^"]+)"', clean)
            if m:
                rewrite = m.group(1).strip()
            m = re.search(r'"confidence"\s*:\s*([0-9.]+)', clean)
            if m:
                try: conf = float(m.group(1))
                except: pass

        if label not in VALID_CLASSES:
            label = "none"

        return RouterClassification(
            classification=label, confidence=conf,
            query_rewrite=rewrite, stage="llm",
            latency_ms=latency_ms, raw_llm_response=raw,
        )

    # ---- Public ----
    def classify(self, utterance: str, context: Optional[list[str]] = None) -> RouterClassification:
        t0 = time.perf_counter()
        context = context or []

        kw = self._keyword_classify(utterance)
        if kw is not None:
            kw.latency_ms = (time.perf_counter() - t0) * 1000
            self.trace.emit("router", "classified", data={
                "stage": kw.stage, "classification": kw.classification,
                "confidence": kw.confidence, "latency_ms": round(kw.latency_ms, 1),
                "matched_keywords": kw.matched_keywords,
            })
            return kw

        llm = self._llm_classify(utterance, context)
        llm.latency_ms = (time.perf_counter() - t0) * 1000
        self.trace.emit("router", "classified", data={
            "stage": llm.stage, "classification": llm.classification,
            "confidence": llm.confidence, "latency_ms": round(llm.latency_ms, 1),
            "query_rewrite": llm.query_rewrite,
        })
        return llm


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    import argparse
    p = argparse.ArgumentParser(description="SENTINEL Router — triage live utterances")
    p.add_argument("--text", required=True)
    p.add_argument("--context", default="", help="Prior context, '|' separated")
    p.add_argument("--region", default="us")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    context = [c.strip() for c in args.context.split("|") if c.strip()] if args.context else []
    agent = RouterAgent(region=args.region)
    result = agent.classify(args.text, context)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    icon = {"none":"·", "officer_violation":"⚠ OFF",
            "citizen_violation":"⚠ CIT", "escalation":"↑ ESC",
            "de_escalation":"✓ DE"}.get(result.classification, "?")
    print("=" * 70)
    print(f"ROUTER  region={args.region}")
    print(f"  Text   : {args.text}")
    if context:
        print(f"  Context: {len(context)} utterances")
    print(f"  Class  : {icon}  {result.classification}  (conf={result.confidence:.2f})")
    print(f"  Stage  : {result.stage}    Latency: {result.latency_ms:.1f}ms")
    if result.query_rewrite:
        print(f"  Query  : \"{result.query_rewrite}\"")
    if result.matched_keywords:
        print(f"  Keys   : {', '.join(result.matched_keywords[:5])}")
    if result.raw_llm_response and "ERROR" in (result.raw_llm_response or ""):
        print(f"  LLM err: {result.raw_llm_response[:200]}")
    print()


if __name__ == "__main__":
    _cli()
