from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db
from .models import Job, utcnow
from .schemas import JobCreate, JobOut

app = FastAPI(title="TaskForge API", version="0.1.0")
DB = Annotated[Session, Depends(get_db)]

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}  # Process health, not a database readiness check.

@app.post("/api/v1/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(data: JobCreate, db: DB) -> Job:
    job = Job(job_type=data.job_type, payload=data.payload, max_attempts=data.max_attempts)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

@app.get("/api/v1/jobs", response_model=list[JobOut])
def list_jobs(db: DB, limit: int = Query(default=25, ge=1, le=100)) -> list[Job]:
    return list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit)).all())

@app.get("/api/v1/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: DB) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.post("/api/v1/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, db: DB) -> Job:
    # Lock ensures two manual retry calls do not mutate the same job concurrently.
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "FAILED":
        raise HTTPException(status_code=409, detail="Only FAILED jobs can be retried")
    job.status = "PENDING"
    job.attempts = 0
    job.result = None
    job.error = None
    job.next_run_at = utcnow()
    db.commit()
    db.refresh(job)
    return job
