# TaskForge — PostgreSQL-backed Job Processing API

A backend engineering portfolio starter: a small background-job system built with **FastAPI**, **SQLAlchemy 2**, and **PostgreSQL**, where independent worker processes claim jobs using row locking (`FOR UPDATE SKIP LOCKED`), retry failures with exponential backoff, and run together under **Docker Compose**.

> **Status:** learning project / MVP. Not production-ready. See [Known limitations](#known-limitations).

## Contents

- [Quick start (Docker)](#quick-start-docker)
- [API reference](#api-reference)
- [Job types](#job-types)
- [Job lifecycle and retries](#job-lifecycle-and-retries)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Running locally without Docker](#running-locally-without-docker)
- [Tests and CI](#tests-and-ci)
- [Project layout](#project-layout)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

## Quick start (Docker)

Requirements: Docker with the Compose plugin.

```bash
docker compose up --build -d
```

This starts four services:

| Service  | Role                                                              |
|----------|-------------------------------------------------------------------|
| `db`     | PostgreSQL 17 on `localhost:5432` (user/password/db: `taskforge`) |
| `init`   | One-shot: creates the tables, then exits                          |
| `api`    | FastAPI on `http://localhost:8000`                                |
| `worker` | Polls for pending jobs and runs them                              |

`api` and `worker` wait until `init` has finished, and `init` waits until the database passes its health check.

Open the interactive docs at **http://localhost:8000/docs**, or try it from the shell:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_type":"sum_numbers","payload":{"numbers":[10,20,30]},"max_attempts":3}'

# Replace <JOB_ID> with the id from the response:
curl http://localhost:8000/api/v1/jobs/<JOB_ID>
```

Windows PowerShell:

```powershell
$job = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/jobs `
  -ContentType 'application/json' `
  -Body '{"job_type":"word_count","payload":{"text":"hello from python"}}'
Invoke-RestMethod http://localhost:8000/api/v1/jobs/$($job.id)
```

Common operations:

```bash
docker compose up -d --scale worker=3   # run 3 workers in parallel
docker compose logs -f worker           # follow worker logs
docker compose down                     # stop (keeps data)
docker compose down -v                  # stop and delete the pgdata volume
```

## API reference

Base URL: `http://localhost:8000`

| Method | Path                         | Description                                                            |
|--------|------------------------------|------------------------------------------------------------------------|
| GET    | `/health`                    | Liveness check. Returns `{"status":"ok"}`. Does **not** check the DB.  |
| POST   | `/api/v1/jobs`               | Create a job. Returns `201` with the job.                              |
| GET    | `/api/v1/jobs?limit=25`      | List the newest jobs (`limit` 1–100, default 25).                      |
| GET    | `/api/v1/jobs/{job_id}`      | Get one job. `404` if not found.                                       |
| POST   | `/api/v1/jobs/{job_id}/retry`| Requeue a `FAILED` job: resets attempts, result, and error. `409` if the job isn't `FAILED`. |

**Create request body**

```json
{
  "job_type": "sum_numbers",
  "payload": { "numbers": [1, 2, 3] },
  "max_attempts": 3
}
```

- `job_type`: `"sum_numbers"` or `"word_count"`. Other values are rejected with `422`.
- `payload`: JSON object. Its contents are checked by the worker, not the API.
- `max_attempts`: optional, 1–10, default 3.

**Job response**

```json
{
  "id": "3f6c…",
  "job_type": "sum_numbers",
  "payload": { "numbers": [1, 2, 3] },
  "status": "COMPLETED",
  "attempts": 1,
  "max_attempts": 3,
  "result": { "sum": 6 },
  "error": null,
  "created_at": "2026-01-01T12:00:00Z",
  "updated_at": "2026-01-01T12:00:01Z",
  "next_run_at": "2026-01-01T12:00:00Z"
}
```

## Job types

| `job_type`    | Payload                          | Result             |
|---------------|----------------------------------|--------------------|
| `sum_numbers` | `{"numbers": [1, 2, 3]}`         | `{"sum": 6}`       |
| `word_count`  | `{"text": "one two three"}`      | `{"count": 3}`     |

`sum_numbers` needs a non-empty list of numbers (booleans are rejected). `word_count` needs a string.

To add a job type:

1. Add a branch to `execute_job` in [app/tasks.py](app/tasks.py).
2. Add the name to the `job_type` `Literal` in [app/schemas.py](app/schemas.py).
3. Add a test in [tests/test_tasks.py](tests/test_tasks.py).

## Job lifecycle and retries

```
            create
              │
              ▼
   ┌──────► PENDING ──── worker claims (attempts += 1) ───► RUNNING
   │                                                          │
   │ backoff, if attempts < max_attempts      ┌── success ────┤
   └──────────────────────────────────────────┤               │
                                              │               ▼
                    POST /retry               │           COMPLETED
   PENDING ◄─────────────────────── FAILED ◄──┘ error and attempts >= max_attempts
```

- When a job fails, the error message is saved to `error` (up to 2000 characters).
- If attempts remain, the job goes back to `PENDING` with `next_run_at = now + min(2^attempts, 60)` seconds. That gives waits of 2s, 4s, 8s, and so on, up to 60s.
- Once `max_attempts` is used up, the job becomes `FAILED`. You can requeue it with `POST /api/v1/jobs/{id}/retry`.

## Architecture

```
Client ──HTTP──► FastAPI (api) ──INSERT/SELECT──► PostgreSQL `jobs` table
                                                        ▲
                       worker 1..N ── poll + FOR UPDATE SKIP LOCKED
```

- The API and the workers are separate processes. They only talk to each other through the `jobs` table.
- **Claiming** ([app/worker.py](app/worker.py)): in one short transaction, a worker picks the oldest due `PENDING` row with `FOR UPDATE SKIP LOCKED`, sets it to `RUNNING`, increases `attempts`, and commits. Because of `SKIP LOCKED`, two workers never claim the same row and never wait on each other's locks.
- **Execution** runs *outside* that transaction, so no row lock is held while the job runs. The outcome is saved in a new transaction, and only if the job is still `RUNNING`.
- The composite index `ix_jobs_claim (status, next_run_at, created_at)` supports the claim query.
- Manual retry locks the row (`FOR UPDATE`), so two retry calls at the same time can't conflict.

## Configuration

Both the API and the worker read these environment variables:

| Variable                | Default                                                              | Used by |
|-------------------------|----------------------------------------------------------------------|---------|
| `DATABASE_URL`          | `postgresql+psycopg://taskforge:taskforge@localhost:5432/taskforge`  | all     |
| `POLL_INTERVAL_SECONDS` | `1`                                                                  | worker  |

[.env.example](.env.example) lists them. The app does **not** load `.env` files by itself, so export the variables in your shell. The defaults already work with the Compose database exposed on `localhost`.

## Running locally without Docker

You still need a PostgreSQL instance. The easiest way is to start only the Compose database:

```bash
docker compose up -d db

python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux:        source .venv/bin/activate
pip install -e ".[dev]"

python -m app.init_db                 # create tables
uvicorn app.main:app --reload         # terminal 1: API on :8000
python -m app.worker                  # terminal 2 (and more): workers
```

Requires Python 3.12+.

## Tests and CI

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

The current tests cover the job handlers in [app/tasks.py](app/tasks.py) and don't need a database.

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push and pull request. It installs the package on Python 3.12, byte-compiles `app/` and `tests/`, and runs `pytest`.

## Project layout

```
app/
  main.py       FastAPI app and HTTP endpoints
  worker.py     Worker loop: claim, execute, record result or retry
  tasks.py      Job handlers (business logic, no DB)
  models.py     SQLAlchemy `Job` model and claim index
  schemas.py    Pydantic request/response models
  database.py   Engine, session factory, DATABASE_URL
  init_db.py    Creates tables (bootstrap only)
tests/          pytest suite
compose.yaml    db + init + api + worker services
Dockerfile      Python 3.12 slim image (default command runs the API)
```

## Known limitations

This is a deliberate MVP. Before using it for real workloads:

- **Stuck jobs:** if a worker crashes mid-job, the job stays `RUNNING` forever. This needs lease expiry or heartbeats, stale-job recovery, and fencing tokens for each attempt.
- **Retry policy:** every error is retried, including validation errors that can never succeed. Permanent and transient failures should be handled differently. Handlers should also be idempotent.
- **Schema management:** tables are created with `create_all`. Alembic migrations should replace it.
- **Health check:** `/health` only shows that the process is alive. It doesn't check that the database is reachable.
- **Missing production features:** authentication and authorization, rate limiting, idempotency keys, payload size limits, structured logging, metrics, graceful shutdown, and integration tests against PostgreSQL.
- **Dependencies:** versions are ranges with no lockfile.
- **Scale:** a PostgreSQL-backed queue is a good fit here for learning. At larger scale, a dedicated message broker may be the better choice.

## Roadmap

1. Add API integration tests backed by PostgreSQL.
2. Recover stale `RUNNING` jobs safely using worker ownership tokens.
3. Introduce Alembic and per-environment configuration.
4. Add idempotency keys and concurrency load tests.
5. Add Prometheus metrics and OpenTelemetry traces.
6. Add Kubernetes manifests, an HPA experiment, and architecture decision records (ADRs).
