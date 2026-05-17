"""SENTINEL FastAPI backend."""
import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from models import Job, init_db, engine, get_session
from pipeline import run_pipeline

UPLOAD_DIR = Path("recordings")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="SENTINEL — Bidirectional Police Accountability API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


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