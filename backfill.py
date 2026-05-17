"""Load existing results/*.json into the database."""
import json
from pathlib import Path
from datetime import datetime
from sqlmodel import Session
from models import Job, init_db, engine

init_db()

results = Path("results").glob("*.json")
with Session(engine) as session:
    for rp in results:
        data = json.loads(rp.read_text(encoding="utf-8"))
        stem = rp.stem  # e.g. "video1_us"
        audio_file = data.get("audio_file", "")
        filename = Path(audio_file).name if audio_file else stem

        job = Job(
            filename=filename,
            file_path=audio_file,
            jurisdiction=data.get("jurisdiction", "US"),
            language=data.get("language", "en"),
            status="done",
            transcript_path=data.get("transcript_path"),
            result_path=str(rp),
            result_data=data,
            events_count=len(data.get("events", [])),
            misconduct_count=len(data.get("routing", {}).get("misconduct_review", [])),
            defense_count=len(data.get("routing", {}).get("officer_defense", [])),
            supervisor_alert_count=len(data.get("routing", {}).get("supervisor_alert", [])),
        )
        session.add(job)
        print(f"✓ {stem}: {job.events_count} events")
    session.commit()
print("Done.")