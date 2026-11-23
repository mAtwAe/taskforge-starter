import logging
import os
import time
from datetime import timedelta
from sqlalchemy import select
from .database import SessionLocal
from .models import Job, utcnow
from .tasks import execute_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("taskforge.worker")


def claim_job() -> str | None:
    # Keep the row lock only for claiming. Never hold it during execution.
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(Job)
            .where(Job.status == "PENDING", Job.next_run_at <= utcnow())
            .order_by(Job.next_run_at, Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "RUNNING"
        job.attempts += 1
        db.flush()
        job_id = job.id
    return job_id


def process_job(job_id: str) -> None:
    # This first-week implementation has no lease recovery after worker crashes.
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "RUNNING":
            return
        job_type, payload = job.job_type, job.payload

    try:
        result = execute_job(job_type, payload)
    except Exception as exc:
        logger.exception("Job failed: %s", job_id)
        with SessionLocal.begin() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "RUNNING":
                return
            job.error = str(exc)[:2000]
            if job.attempts >= job.max_attempts:
                job.status = "FAILED"
            else:
                job.status = "PENDING"
                job.next_run_at = utcnow() + timedelta(seconds=min(2 ** job.attempts, 60))
    else:
        with SessionLocal.begin() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "RUNNING":
                return
            job.result = result
            job.error = None
            job.status = "COMPLETED"
        logger.info("Job completed: %s", job_id)


def main() -> None:
    interval = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
    logger.info("Worker started")
    while True:
        try:
            job_id = claim_job()
            if job_id:
                process_job(job_id)
            else:
                time.sleep(interval)
        except Exception:
            logger.exception("Worker loop error")
            time.sleep(interval)

if __name__ == "__main__":
    main()
