"""SQLModel schema for SENTINEL audit jobs."""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session
from sqlalchemy import Column, JSON


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    filename: str
    file_path: str
    jurisdiction: str  # "US", "EU", "Italy"
    vertical: str = Field(default="police")  # "police" | "corporate_security"
    language: str = "en"

    status: str = "pending"  # pending, transcribing, analyzing, done, error
    error_message: Optional[str] = None

    transcript_path: Optional[str] = None
    result_path: Optional[str] = None

    # Cached summary for fast list view
    events_count: int = 0
    misconduct_count: int = 0
    defense_count: int = 0
    supervisor_alert_count: int = 0

    # Full result JSON (for /events endpoint)
    result_data: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # Council pipeline (v2 — adversarial 4-agent)
    council_status: str = Field(default="not_run")        # not_run | running | done | error
    council_path: Optional[str] = None                    # path to results/council/{id}_council.json
    council_headline: Optional[str] = None                # cached for list view
    council_verdict: Optional[str] = None                 # officer_justified | officer_at_fault | mixed | inconclusive
    council_severity: Optional[str] = None                # none | low | medium | high | critical
    council_wall_sec: Optional[float] = None
    council_started_at: Optional[datetime] = None
    council_completed_at: Optional[datetime] = None
    council_error: Optional[str] = None


DATABASE_URL = "sqlite:///bodycam.db"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session