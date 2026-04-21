# distributed-job-processing-system

Phase 1 is a minimal local job processing system built with FastAPI, Celery, RabbitMQ, and Postgres.

## Phase 1 layout

```text
app/
  api/
  common/
  worker/
infra/
  docker/
alembic/
tests/
```

## Prerequisites

- uv
- Docker Desktop or Docker Engine with Compose

## Run with Docker Compose

From the repository root:

```bash
docker compose up --build
```

The API will be available at <http://localhost:8000>.

## Run locally with uv

Create a local environment file if you want to run the API or worker outside Docker:

```bash
copy .env.example .env
uv sync
```

Start the API:

```bash
uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

Apply migrations:

```bash
uv run alembic upgrade head
```

Seed deterministic dummy jobs:

```bash
uv run seed-dummy-jobs --truncate-first
```

Start the worker:

```bash
uv run celery -A app.worker.celery_app:celery_app worker --loglevel=info
```

## API usage

Health check:

```bash
curl http://localhost:8000/health
```

Submit a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"input_value":"hello-world"}'
```

Example response:

```json
{
  "id": "6f98c765-4070-4d44-a576-5ee0f7f9af84",
  "input_value": "hello-world",
  "status": "queued",
  "result": null,
  "error_message": null,
  "created_at": "2026-04-19T00:00:00.000000Z",
  "updated_at": "2026-04-19T00:00:00.000000Z"
}
```

Fetch job status:

```bash
curl http://localhost:8000/jobs/<job-id>
```

The job status flows through `queued`, `processing`, and `completed`, or `failed` if the worker raises an exception.

## Reproducible seed data

Use the seed command to populate the `jobs` table with the same deterministic demo rows every time.

Safe upsert mode updates the fixed seeded rows without deleting other job records:

```bash
uv run seed-dummy-jobs
```

Exact reset mode deletes existing job rows first, then inserts the same seeded dataset:

```bash
uv run seed-dummy-jobs --truncate-first
```

If the Docker stack is already running and you want to seed the database from inside the API container:

```bash
docker compose exec api python -m app.common.seed_jobs --truncate-first
```
