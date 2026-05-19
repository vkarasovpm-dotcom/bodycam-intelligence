"""SENTINEL Transcription Agent — Speechmatics real-time + batch combo.

Demonstrates 6 sponsor features in one pipeline:
  1. Real-time WebSocket streaming (partials + finals) for live UI effect
  2. Speaker diarization (S1, S2, ...)
  3. Real-time translation (Italian/German -> English)
  4. End-of-utterance detection (conversation_config)
  5. Batch sentiment analysis (positive / negative / neutral per segment)
  6. Batch summarization + topic detection (conversational summary)

Architecture:
  RT pass  -> live diarized transcript stream, drives UI in real time
  Batch    -> sentiment + summary + topics, attached after RT completes
"""
from __future__ import annotations
import asyncio
import os
import json
import time
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

from speechmatics.rt import (
    AsyncClient as RTClient,
    AudioFormat,
    AudioEncoding,
    TranscriptionConfig as RTConfig,
    TranslationConfig,                   # <-- Новый отдельный конфиг для перевода
    TranscriptResult,
    ServerMessageType,
    ConversationConfig,
)

from agents.base import Trace, logger


# ============ DATA MODELS ============

@dataclass
class Utterance:
    speaker: str
    text: str
    start: float
    end: float
    translation: Optional[str] = None
    sentiment: Optional[str] = None
    confidence: float = 1.0
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranscriptionResult_:
    language: str
    target_language: Optional[str]
    utterances: list[Utterance] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    summary: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    raw_text: str = ""
    duration_sec: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "target_language": self.target_language,
            "utterances": [u.to_dict() for u in self.utterances],
            "speakers": self.speakers,
            "summary": self.summary,
            "topics": self.topics,
            "raw_text": self.raw_text,
            "duration_sec": self.duration_sec,
        }


# ============ AUDIO PREP ============

def _ensure_16khz_pcm(audio_path: str) -> bytes:
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-loglevel", "error",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return result.stdout


async def _stream_file(client: RTClient, audio_bytes: bytes,
                       chunk_size: int = 4096,
                       realtime_factor: float = 4.0) -> None:
    bytes_per_sec = 16000 * 2
    chunk_duration = chunk_size / bytes_per_sec
    sleep_per_chunk = chunk_duration / max(realtime_factor, 0.1)
    for i in range(0, len(audio_bytes), chunk_size):
        chunk = audio_bytes[i:i + chunk_size]
        await client.send_audio(chunk)
        await asyncio.sleep(sleep_per_chunk)


# ============ TRANSCRIPTION AGENT ============

class TranscriptionAgent:
    """Hybrid RT + batch transcription with full sponsor feature coverage."""
    
    def __init__(self, trace: Trace,
                 language: str = "en",
                 target_language: Optional[str] = None,
                 enable_translation: bool = False,
                 enable_sentiment: bool = True,
                 enable_summary: bool = True,
                 enable_topics: bool = True,
                 realtime_factor: float = 4.0,
                 on_partial: Optional[Callable[[str, str], None]] = None,
                 on_final: Optional[Callable[[Utterance], None]] = None) -> None:
        self.trace = trace
        self.language = language
        self.target_language = target_language if enable_translation else None
        self.enable_translation = enable_translation
        self.enable_sentiment = enable_sentiment
        self.enable_summary = enable_summary
        self.enable_topics = enable_topics
        self.realtime_factor = realtime_factor
        self.on_partial = on_partial
        self.on_final = on_final
        
        self.api_key = os.environ["SPEECHMATICS_API_KEY"]
        self.utterances: list[Utterance] = []
        self.raw_text_parts: list[str] = []
        self.speakers_seen: set[str] = set()
        self.summary_text: Optional[str] = None
        self.topics: list[str] = []
    
    # ---------- RT pass ----------
    
    def _build_rt_configs(self) -> tuple[RTConfig, Optional[TranslationConfig]]:
        """Возвращает кортеж из TranscriptionConfig и TranslationConfig."""
        t_config = RTConfig(
            language=self.language,
            max_delay=0.7,
            enable_partials=True,
            diarization="speaker",
            conversation_config=ConversationConfig(
                end_of_utterance_silence_trigger=0.5,
            )
        )
        
        tl_config = None
        if self.enable_translation and self.target_language and self.target_language != self.language:
            tl_config = TranslationConfig(
                target_languages=[self.target_language],
                enable_partials=True
            )
            
        return t_config, tl_config
    
    def _handle_partial(self, msg) -> None:
        try:
            r = TranscriptResult.from_message(msg)
            text = r.metadata.transcript if r.metadata else ""
            if text and self.on_partial:
                self.on_partial(text, "live")
        except Exception as e:
            logger.warning(f"partial parse: {e}")
    
    def _handle_final(self, msg) -> None:
        try:
            results = msg.get("results", []) if isinstance(msg, dict) else []
            current_speaker = None
            buf, seg_conf = [], []
            seg_start, seg_end = None, None
            
            for r in results:
                alts = r.get("alternatives", [])
                if not alts:
                    continue
                alt = alts[0]
                content = alt.get("content", "")
                spk = alt.get("speaker", "UU")
                if current_speaker is None:
                    current_speaker = spk
                    seg_start = r.get("start_time", 0.0)
                if spk != current_speaker and buf:
                    self._emit_utterance(current_speaker, buf, seg_start, seg_end or 0.0, seg_conf)
                    buf, seg_conf = [], []
                    current_speaker = spk
                    seg_start = r.get("start_time", 0.0)
                buf.append(content)
                seg_end = r.get("end_time", seg_end)
                seg_conf.append(alt.get("confidence", 1.0))
            if buf and current_speaker is not None:
                self._emit_utterance(current_speaker, buf, seg_start or 0.0, seg_end or 0.0, seg_conf)
        except Exception as e:
            logger.warning(f"final parse: {e}")
    
    def _emit_utterance(self, speaker, words, start, end, confs):
        text = ""
        for w in words:
            if w in ",.!?;:":
                text += w
            else:
                text += (" " + w) if text else w
        text = text.strip()
        if not text:
            return
        avg_conf = sum(confs) / len(confs) if confs else 1.0
        utt = Utterance(speaker=speaker, text=text, start=start, end=end, confidence=avg_conf)
        self.utterances.append(utt)
        self.raw_text_parts.append(f"[{speaker}] {text}")
        self.speakers_seen.add(speaker)
        if self.on_final:
            self.on_final(utt)
        self.trace.emit(
            "transcription", "utterance_finalized",
            data={"speaker": speaker, "chars": len(text), "start": round(start, 2)},
        )
    
    def _handle_translation(self, msg) -> None:
        try:
            data = msg if isinstance(msg, dict) else {}
            results = data.get("results", [])
            translated = " ".join(r.get("content", "") for r in results).strip()
            if not translated:
                return
            for utt in reversed(self.utterances):
                if utt.translation is None:
                    utt.translation = translated
                    self.trace.emit(
                        "transcription", "translation_added",
                        data={"speaker": utt.speaker, "target": self.target_language},
                    )
                    break
        except Exception as e:
            logger.warning(f"translation parse: {e}")
    
    async def _rt_pass(self, audio_bytes: bytes) -> None:
        audio_format = AudioFormat(
            encoding=AudioEncoding.PCM_S16LE,
            sample_rate=16000,
            chunk_size=4096,
        )
        transcription_cfg, translation_cfg = self._build_rt_configs()
        
        async with RTClient(api_key=self.api_key) as client:
            
            @client.on(ServerMessageType.ADD_PARTIAL_TRANSCRIPT)
            def _p(msg):
                self._handle_partial(msg)
            
            @client.on(ServerMessageType.ADD_TRANSCRIPT)
            def _f(msg):
                self._handle_final(msg)
            
            for name in ("ADD_PARTIAL_TRANSLATION", "ADD_TRANSLATION"):
                evt = getattr(ServerMessageType, name, None)
                if evt is not None:
                    client.on(evt)(lambda m: self._handle_translation(m))
            
            # Передаем translation_config как отдельный аргумент для новых версий SDK
            kwargs = {
                "transcription_config": transcription_cfg,
                "audio_format": audio_format,
            }
            if translation_cfg:
                kwargs["translation_config"] = translation_cfg
                
            await client.start_session(**kwargs)
            
            await _stream_file(client, audio_bytes,
                               chunk_size=4096,
                               realtime_factor=self.realtime_factor)
            await asyncio.sleep(2.0)
    
    # ---------- Batch pass (sentiment + summary + topics) ----------
    
    async def _batch_pass(self, audio_path: str) -> None:
        if not (self.enable_sentiment or self.enable_summary or self.enable_topics):
            return
        try:
            from speechmatics.batch import (
                AsyncClient as BatchClient,
                JobConfig, JobType,
                TranscriptionConfig as BatchTConfig,
                SentimentAnalysisConfig,
                TopicDetectionConfig,
                SummarizationConfig,
            )
        except Exception as e:
            logger.warning(f"speechmatics-batch not available: {e}")
            self.trace.emit("transcription", "batch_skipped",
                            data={"reason": "speechmatics-batch missing"})
            return
        
        self.trace.emit("transcription", "batch_pass_start",
                        data={"sentiment": self.enable_sentiment,
                              "summary": self.enable_summary,
                              "topics": self.enable_topics})
        
        cfg = JobConfig(
            type=JobType.TRANSCRIPTION,
            transcription_config=BatchTConfig(language=self.language, diarization="speaker"),
        )
        if self.enable_sentiment:
            cfg.sentiment_analysis_config = SentimentAnalysisConfig()
        if self.enable_topics:
            cfg.topic_detection_config = TopicDetectionConfig()
        if self.enable_summary:
            cfg.summarization_config = SummarizationConfig(
                content_type="conversational",
                summary_length="brief",
            )
        
        try:
            async with BatchClient(api_key=self.api_key) as bc:
                job = await bc.submit_job(audio_path, config=cfg)
                result = await bc.wait_for_completion(job.id)
            
            # sentiment -> attach to utterances by time overlap
            if self.enable_sentiment and getattr(result, "sentiment_analysis", None):
                segments = result.sentiment_analysis.get("segments", []) if isinstance(result.sentiment_analysis, dict) else []
                tagged = 0
                for seg in segments:
                    sent = (seg.get("sentiment") or "").lower()
                    start = seg.get("start_time", 0)
                    for utt in self.utterances:
                        if utt.start <= start <= utt.end and utt.sentiment is None:
                            utt.sentiment = sent
                            tagged += 1
                            break
                self.trace.emit("transcription", "sentiment_applied",
                                data={"segments": len(segments), "tagged_utterances": tagged})
            
            # summary
            if self.enable_summary and getattr(result, "summary", None):
                self.summary_text = result.summary.get("content") if isinstance(result.summary, dict) else str(result.summary)
                self.trace.emit("transcription", "summary_received",
                                data={"chars": len(self.summary_text or "")})
            
            # topics
            if self.enable_topics and getattr(result, "topics", None):
                topics_data = result.topics if isinstance(result.topics, dict) else {}
                if "summary" in topics_data and "overall" in topics_data["summary"]:
                    self.topics = [t for t, c in topics_data["summary"]["overall"].items() if c > 0]
                self.trace.emit("transcription", "topics_detected",
                                data={"topics": self.topics})
        except Exception as e:
            logger.warning(f"batch pass failed: {e}")
            self.trace.emit("transcription", "batch_failed",
                            data={"error": str(e)[:200]})
    
    # ---------- Public API ----------
    
    async def transcribe_file(self, audio_path: str) -> TranscriptionResult_:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(audio_path)
        
        self.trace.emit(
            "transcription", "session_start",
            data={
                "file": path.name,
                "language": self.language,
                "target_language": self.target_language,
                "translation": self.enable_translation,
                "sentiment": self.enable_sentiment,
                "summary": self.enable_summary,
                "topics": self.enable_topics,
                "realtime_factor": self.realtime_factor,
            },
            reasoning="Hybrid pipeline: Speechmatics RT (diarization+translation+partials) "
                     "+ Batch (sentiment+summary+topics) — all 6 sponsor features in one job."
        )
        
        audio_bytes = _ensure_16khz_pcm(str(path))
        duration_sec = len(audio_bytes) / (16000 * 2)
        self.trace.emit("transcription", "audio_decoded",
                        data={"bytes": len(audio_bytes), "duration_sec": round(duration_sec, 2)})
        
        t0 = time.time()
        await self._rt_pass(audio_bytes)
        rt_elapsed = time.time() - t0
        self.trace.emit("transcription", "rt_pass_complete",
                        data={"utterances": len(self.utterances),
                              "speakers": len(self.speakers_seen),
                              "wall_sec": round(rt_elapsed, 2)})
        
        t1 = time.time()
        await self._batch_pass(str(path))
        batch_elapsed = time.time() - t1
        self.trace.emit("transcription", "batch_pass_complete",
                        data={"wall_sec": round(batch_elapsed, 2)})
        
        return TranscriptionResult_(
            language=self.language,
            target_language=self.target_language,
            utterances=self.utterances,
            speakers=sorted(self.speakers_seen),
            summary=self.summary_text,
            topics=self.topics,
            raw_text="\n".join(self.raw_text_parts),
            duration_sec=duration_sec,
        )


# ============ CLI ============

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m agents.transcription_agent <audio_file> [language]")
        sys.exit(1)
    
    audio = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "en"
    
    trace = Trace()
    agent = TranscriptionAgent(
        trace=trace,
        language=lang,
        target_language="en" if lang != "en" else None,
        enable_translation=(lang != "en"),
        enable_sentiment=True,
        enable_summary=True,
        enable_topics=True,
        realtime_factor=8.0,
        on_partial=lambda text, spk: print(f"  ~ {text}", flush=True),
        on_final=lambda u: print(f"  ✓ [{u.speaker}] {u.text}", flush=True),
    )
    
    result = asyncio.run(agent.transcribe_file(audio))
    
    print("\n" + "="*60)
    print("TRANSCRIPTION RESULT")
    print("="*60)
    print(f"Language:    {result.language}")
    print(f"Target lang: {result.target_language}")
    print(f"Duration:    {result.duration_sec:.1f}s")
    print(f"Speakers:    {result.speakers}")
    print(f"Utterances:  {len(result.utterances)}")
    print(f"Summary:     {result.summary}")
    print(f"Topics:      {result.topics}")
    print(f"\nUtterances with sentiment:")
    for u in result.utterances:
        sent = f" [{u.sentiment}]" if u.sentiment else ""
        trans = f" -> {u.translation}" if u.translation else ""
        print(f"  [{u.speaker}] {u.text}{sent}{trans}")
    
    print("\n" + "="*60)
    print(f"TRACE ({len(trace.to_list())} events)")
    print("="*60)
    for ev in trace.to_list():
        print(f"  {ev['agent']:15s} {ev['action']:30s} {ev['data']}")

    # Save result + trace as JSON for downstream agents
    from pathlib import Path
    from dataclasses import asdict
    audio_path = Path(sys.argv[1])
    out_path = Path("results/standard") / (audio_path.stem + "_transcript.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    payload["trace"] = trace.to_list()
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n✓ Saved transcript: {out_path}")