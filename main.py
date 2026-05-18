"""SENTINEL FastAPI backend."""
import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from models import Job, init_db, engine, get_session
from pipeline import run_pipeline

log = logging.getLogger("sentinel.main")

UPLOAD_DIR = Path("recordings")
UPLOAD_DIR.mkdir(exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup warmup: DB init + retrieval index/embedder pre-load.

    Without this, the first /api/live request pays a ~6-9s cold start
    (downloads MiniLM weights + loads FAISS). After warmup all routes are warm.
    """
    init_db()
    log.info("[warmup] starting retrieval warmup (MiniLM + FAISS indexes)")
    try:
        from agents.base import Trace
        from agents.retrieval_agent import RetrievalAgent
        warm_trace = Trace()
        retr = RetrievalAgent(trace=warm_trace)
        for region in ("us", "eu", "it"):
            retr.search("warmup query", region=region, top_k=1)
        log.info("[warmup] retrieval ready for regions: us, eu, it")
    except Exception as e:
        log.warning(f"[warmup] retrieval warmup failed: {e}")
    yield
    # No teardown needed


app = FastAPI(
    title="SENTINEL — Bidirectional Police Accountability API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_methods=["*"],
    allow_headers=["*"],
)


async def process_job(job_id: int):
    """Background worker — runs pipeline and updates DB."""
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            return
        try:
            job.status = "transcribing"
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

            result = await run_pipeline(
                audio_path=job.file_path,
                jurisdiction=job.jurisdiction,
                language=job.language,
            )

            job.status = "done"
            job.transcript_path = result["transcript_path"]
            job.result_path = result["result_path"]
            job.result_data = result
            job.events_count = len(result["events"])
            job.misconduct_count = len(result["routing"]["misconduct_review"])
            job.defense_count = len(result["routing"]["officer_defense"])
            job.supervisor_alert_count = len(result["routing"]["supervisor_alert"])
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()
        except Exception as e:
            job.status = "error"
            job.error_message = str(e)[:500]
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()


@app.post("/api/audit/upload")
async def upload_audit(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    jurisdiction: str = Form("US"),
    language: str = Form("en"),
    vertical: str = Form("police"),
    session: Session = Depends(get_session),
):
    if jurisdiction not in ("US", "EU", "Italy"):
        raise HTTPException(400, "jurisdiction must be US, EU, or Italy")
    if vertical not in ("police", "corporate_security"):
        raise HTTPException(400, "vertical must be police or corporate_security")
    if vertical == "corporate_security" and jurisdiction != "EU":
        raise HTTPException(400, "corporate_security is EU-only for now")
    
    safe_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    target = UPLOAD_DIR / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    job = Job(
        filename=file.filename,
        file_path=str(target),
        jurisdiction=jurisdiction,
        language=language,
        vertical=vertical,
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    background_tasks.add_task(asyncio.run, process_job(job.id))

    return {"job_id": job.id, "status": "pending", "filename": file.filename}


@app.get("/api/audit/list")
def list_audits(
    session: Session = Depends(get_session),
    limit: int = 50,
    vertical: str | None = None,
):
    query = select(Job).order_by(Job.created_at.desc())
    if vertical:
        query = query.where(Job.vertical == vertical)
    jobs = session.exec(query.limit(limit)).all()
    return [
        {
            "id": j.id,
            "filename": j.filename,
            "jurisdiction": j.jurisdiction,
            "vertical": j.vertical,
            "status": j.status,
            "created_at": j.created_at.isoformat(),
            "events_count": j.events_count,
            "misconduct_count": j.misconduct_count,
            "defense_count": j.defense_count,
            "supervisor_alert_count": j.supervisor_alert_count,
        }
        for j in jobs
    ]


@app.get("/api/audit/{job_id}")
def get_audit(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "id": job.id,
        "filename": job.filename,
        "jurisdiction": job.jurisdiction,
        "vertical": job.vertical,
        "language": job.language,
        "status": job.status,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "events_count": job.events_count,
        "misconduct_count": job.misconduct_count,
        "defense_count": job.defense_count,
        "supervisor_alert_count": job.supervisor_alert_count,
        "result": job.result_data,
    }


@app.get("/api/audit/{job_id}/events")
def get_audit_events(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not job.result_data:
        return {"events": [], "status": job.status}
    return {
        "events": job.result_data.get("events", []),
        "routing": job.result_data.get("routing", {}),
        "metadata": job.result_data.get("metadata", {}),
        "status": job.status,
    }


@app.get("/")
def health():
    return {"job_id": job.id, "status": "pending", "filename": file.filename, "vertical": vertical}



# ============ COUNCIL ENDPOINTS (v2 — adversarial pipeline) ============

from pipeline_v2 import run_council
import json as _json


def _process_council_sync(job_id: int) -> None:
    """Background runner: launches pipeline_v2 as a subprocess.

    We use a subprocess instead of calling run_council() in-process because
    speechmatics-rt's async client hangs when launched inside FastAPI's
    BackgroundTasks threadpool (event-loop conflict). Subprocess fully
    isolates the event loop and matches the proven CLI execution path.
    """
    import subprocess
    import sys
    import os as _os
    from models import Job, engine
    from sqlmodel import Session
    from datetime import datetime as _dt

    with Session(engine) as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        job.council_status = "running"
        job.council_started_at = _dt.utcnow()
        job.council_error = None
        s.add(job); s.commit(); s.refresh(job)
        audio_path = job.file_path
        region = (job.jurisdiction or "US").lower()
        if region == "italy":
            region = "eu"
        vertical = job.vertical or "police"
        language = job.language or "en"

    log_path = Path("results/council") / f"{job_id}_council.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cmd = [
            sys.executable, "-m", "pipeline_v2",
            audio_path, region, vertical, language,
        ]
        with log_path.open("w", encoding="utf-8") as logf:
            proc = subprocess.run(
                cmd,
                cwd="/opt/sentinel",
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=600,
                env=_os.environ.copy(),
            )

        stem = Path(audio_path).stem
        src_path = Path("results/council") / f"{stem}_council.json"
        stable_path = Path("results/council") / f"{job_id}_council.json"
        if src_path.exists():
            stable_path.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")
            report = _json.loads(stable_path.read_text(encoding="utf-8"))
        else:
            report = None

        with Session(engine) as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            if proc.returncode != 0 or report is None:
                job.council_status = "error"
                tail = ""
                try:
                    tail = log_path.read_text(encoding="utf-8")[-500:]
                except Exception:
                    pass
                job.council_error = f"subprocess rc={proc.returncode}; tail: {tail}"[:800]
            else:
                job.council_status = "done" if report.get("status") == "ok" else "error"
                job.council_path = str(stable_path)
                job.council_headline = (report.get("verdict") or {}).get("headline")
                job.council_verdict = (report.get("verdict") or {}).get("overall_verdict")
                job.council_severity = (report.get("verdict") or {}).get("overall_severity")
                job.council_wall_sec = report.get("wall_sec")
                if report.get("error"):
                    job.council_error = report["error"]
            job.council_completed_at = _dt.utcnow()
            s.add(job); s.commit()

    except subprocess.TimeoutExpired:
        with Session(engine) as s:
            job = s.get(Job, job_id)
            if job:
                job.council_status = "error"
                job.council_error = "subprocess timeout after 600s"
                job.council_completed_at = _dt.utcnow()
                s.add(job); s.commit()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[council job={job_id}] EXCEPTION:\n{tb}", flush=True)
        with Session(engine) as s:
            job = s.get(Job, job_id)
            if job:
                job.council_status = "error"
                job.council_error = (str(e) + " :: " + tb[-400:])[:800]
                job.council_completed_at = _dt.utcnow()
                s.add(job); s.commit()


@app.post("/api/audit/{job_id}/council/run")
def council_run(job_id: int, background_tasks: BackgroundTasks,
                session: Session = Depends(get_session)):
    """Launch the 4-agent adversarial council for an existing audit."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if not Path(job.file_path).exists():
        raise HTTPException(400, f"audio file missing: {job.file_path}")
    if job.council_status == "running":
        from datetime import datetime as _dt, timedelta as _td
        started = job.council_started_at
        if started and (_dt.utcnow() - started) < _td(minutes=5):
            return {"job_id": job_id, "council_status": "running",
                    "message": "already in progress",
                    "started_at": started.isoformat()}
        # else: treat as stale, fall through to restart

    background_tasks.add_task(_process_council_sync, job_id)
    return {"job_id": job_id, "council_status": "queued"}


@app.get("/api/audit/{job_id}/council")
def council_get(job_id: int, session: Session = Depends(get_session)):
    """Return the full CouncilReport JSON for a job (if available)."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")

    payload: dict = {
        "job_id": job_id,
        "filename": job.filename,
        "council_status": job.council_status,
        "council_headline": job.council_headline,
        "council_verdict": job.council_verdict,
        "council_severity": job.council_severity,
        "council_wall_sec": job.council_wall_sec,
        "council_started_at": job.council_started_at.isoformat() if job.council_started_at else None,
        "council_completed_at": job.council_completed_at.isoformat() if job.council_completed_at else None,
        "council_error": job.council_error,
        "report": None,
    }
    if job.council_path and Path(job.council_path).exists():
        try:
            payload["report"] = _json.loads(Path(job.council_path).read_text(encoding="utf-8"))
        except Exception as e:
            payload["report_error"] = str(e)[:200]
    return payload


@app.get("/api/audit/{job_id}/council/trace")
def council_trace(job_id: int, session: Session = Depends(get_session)):
    """Return only the merged trace events (for Reasoning Trace UI tab)."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if not job.council_path or not Path(job.council_path).exists():
        return {"job_id": job_id, "council_status": job.council_status, "trace": []}
    data = _json.loads(Path(job.council_path).read_text(encoding="utf-8"))
    return {"job_id": job_id,
            "council_status": job.council_status,
            "trace": data.get("trace", [])}


@app.get("/api/audit/council/list")
def council_list(session: Session = Depends(get_session)):
    """List all jobs that have a council run (any status)."""
    rows = session.exec(
        select(Job).where(Job.council_status != "not_run").order_by(Job.id.desc())
    ).all()
    return [
        {
            "job_id": j.id,
            "filename": j.filename,
            "jurisdiction": j.jurisdiction,
            "vertical": j.vertical,
            "council_status": j.council_status,
            "council_headline": j.council_headline,
            "council_verdict": j.council_verdict,
            "council_severity": j.council_severity,
            "council_wall_sec": j.council_wall_sec,
        }
        for j in rows
    ]


# ---------------------------------------------------------------------------
# LIVE REPLAY — Server-Sent Events
# ---------------------------------------------------------------------------
# Streams a precomputed session.json back to the frontend, replaying events
# in real time according to their original "t" timestamps. The frontend can
# attach to GET /api/live/replay/{session_id} as an EventSource and receive
# utterance / rapid_alert / deep_scan_* / verdict_update events live.
# ---------------------------------------------------------------------------

import json as _sse_json
import os as _sse_os
from fastapi.responses import StreamingResponse as _StreamingResponse

LIVE_DIR = Path("results/live")


@app.get("/api/live/sessions")
async def list_live_sessions():
    """List all precomputed live sessions available for replay."""
    if not LIVE_DIR.exists():
        return {"sessions": []}
    sessions = []
    for p in sorted(LIVE_DIR.glob("*_session.json")):
        try:
            d = _sse_json.loads(p.read_text())
            stats = d.get("stats", {})
            fv = d.get("final_verdict") or {}
            sessions.append({
                "session_id": d.get("session_id"),
                "region": d.get("region"),
                "file": p.name,
                "size_bytes": p.stat().st_size,
                "utterances": stats.get("total_utterances"),
                "rapid_alerts": stats.get("rapid_alerts"),
                "deep_violations": stats.get("deep_violations"),
                "rebuttals": stats.get("rebuttals"),
                "final_verdict": fv.get("overall_verdict"),
                "final_severity": fv.get("overall_severity"),
                "headline": fv.get("headline"),
            })
        except Exception as e:
            sessions.append({"file": p.name, "error": str(e)})
    return {"sessions": sessions}


@app.get("/api/live/replay/{session_id}")
async def replay_session(session_id: str, speed: float = 1.0, real_time: bool = True):
    """
    Stream a precomputed session as SSE.

    Query params:
        speed     : playback multiplier (1.0 = real time, 4.0 = 4x faster). Default 1.0.
        real_time : if False, dump all events back-to-back (good for fast demos
                    and unit testing the frontend). Default True.

    Event format:
        event: <kind>
        data: <json>

    Kinds emitted: session_start, utterance, rapid_alert, router_skip,
    deep_scan_started, deep_scan_completed, verdict_update, session_end.
    """
    path = LIVE_DIR / f"{session_id}_session.json"
    if not path.exists():
        raise HTTPException(404, f"session not found: {session_id}")

    try:
        data = _sse_json.loads(path.read_text())
    except Exception as e:
        raise HTTPException(500, f"failed to parse session: {e}")

    events = data.get("events", []) or []
    # Sort by t just in case
    events = sorted(events, key=lambda e: e.get("t", 0.0))

    async def gen():
        # session_start envelope
        start_payload = {
            "session_id": data.get("session_id"),
            "region": data.get("region"),
            "vertical": data.get("vertical"),
            "n_events": len(events),
            "stats": data.get("stats", {}),
        }
        yield f"event: session_start\ndata: {_sse_json.dumps(start_payload)}\n\n"

        last_t = 0.0
        wall_start = asyncio.get_event_loop().time()

        for evt in events:
            t = float(evt.get("t", 0.0))

            if real_time and speed > 0:
                # Pace events to their original timestamps (scaled by speed)
                target_wall = wall_start + (t / max(speed, 0.01))
                now = asyncio.get_event_loop().time()
                delay = target_wall - now
                if delay > 0:
                    await asyncio.sleep(min(delay, 30.0))  # cap at 30s safeguard

            kind = evt.get("kind", "event")
            payload = _sse_json.dumps(evt, ensure_ascii=False)
            yield f"event: {kind}\ndata: {payload}\n\n"
            last_t = t

        # Final verdict envelope (frontend convenience — same as last verdict_update)
        final = data.get("final_verdict")
        if final:
            yield f"event: final_verdict\ndata: {_sse_json.dumps(final, ensure_ascii=False)}\n\n"

        end_payload = {
            "session_id": data.get("session_id"),
            "last_t": last_t,
            "n_events_emitted": len(events),
        }
        yield f"event: session_end\ndata: {_sse_json.dumps(end_payload)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable nginx/caddy buffering
        "Connection": "keep-alive",
    }
    return _StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


# ---------------------------------------------------------------------------
# LIVE REPLAY — Server-Sent Events
# ---------------------------------------------------------------------------
import json as _sse_json
from fastapi.responses import StreamingResponse as _StreamingResponse

LIVE_DIR = Path("results/live")


@app.get("/api/live/sessions")
async def list_live_sessions():
    """List all precomputed live sessions available for replay."""
    if not LIVE_DIR.exists():
        return {"sessions": []}
    sessions = []
    for p in sorted(LIVE_DIR.glob("*_session.json")):
        try:
            d = _sse_json.loads(p.read_text())
            stats = d.get("stats", {})
            fv = d.get("final_verdict") or {}
            sessions.append({
                "session_id": d.get("session_id"),
                "region": d.get("region"),
                "file": p.name,
                "size_bytes": p.stat().st_size,
                "utterances": stats.get("total_utterances"),
                "rapid_alerts": stats.get("rapid_alerts"),
                "deep_violations": stats.get("deep_violations"),
                "rebuttals": stats.get("rebuttals"),
                "final_verdict": fv.get("overall_verdict"),
                "final_severity": fv.get("overall_severity"),
                "headline": fv.get("headline"),
            })
        except Exception as e:
            sessions.append({"file": p.name, "error": str(e)})
    return {"sessions": sessions}


@app.get("/api/live/replay/{session_id}")
async def replay_session(session_id: str, speed: float = 1.0, real_time: bool = True):
    """Stream a precomputed session as Server-Sent Events."""
    path = LIVE_DIR / f"{session_id}_session.json"
    if not path.exists():
        raise HTTPException(404, f"session not found: {session_id}")
    try:
        data = _sse_json.loads(path.read_text())
    except Exception as e:
        raise HTTPException(500, f"failed to parse session: {e}")

    events = sorted(data.get("events", []) or [], key=lambda e: e.get("t", 0.0))

    async def gen():
        start_payload = {
            "session_id": data.get("session_id"),
            "region": data.get("region"),
            "vertical": data.get("vertical"),
            "n_events": len(events),
            "stats": data.get("stats", {}),
        }
        yield f"event: session_start\ndata: {_sse_json.dumps(start_payload)}\n\n"

        last_t = 0.0
        wall_start = asyncio.get_event_loop().time()
        for evt in events:
            t = float(evt.get("t", 0.0))
            if real_time and speed > 0:
                target_wall = wall_start + (t / max(speed, 0.01))
                now = asyncio.get_event_loop().time()
                delay = target_wall - now
                if delay > 0:
                    await asyncio.sleep(min(delay, 30.0))
            kind = evt.get("kind", "event")
            payload = _sse_json.dumps(evt, ensure_ascii=False)
            yield f"event: {kind}\ndata: {payload}\n\n"
            last_t = t

        final = data.get("final_verdict")
        if final:
            yield f"event: final_verdict\ndata: {_sse_json.dumps(final, ensure_ascii=False)}\n\n"
        yield f"event: session_end\ndata: {_sse_json.dumps({'session_id': data.get('session_id'), 'last_t': last_t, 'n_events_emitted': len(events)})}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return _StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
