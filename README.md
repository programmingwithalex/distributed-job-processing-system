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
- pnpm
- Docker Desktop or Docker Engine with Compose

## Run with Docker Compose

From the repository root:

```bash
docker compose up --build
```

The frontend will be available at <http://localhost:5173> and the API will be available at <http://localhost:8000>.

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

## Run the React frontend

The repository includes a small React + TypeScript dashboard under `frontend/`.

Install frontend dependencies:

```bash
cd frontend
pnpm install
```

Start the frontend dev server:

```bash
pnpm dev
```

The frontend runs on <http://localhost:5173> and proxies API requests to the FastAPI server on <http://localhost:8000> during local development.

The Docker Compose frontend service uses the same dashboard and proxies API traffic to the `api` container automatically.

Build the frontend:

```bash
pnpm build
```

Run Playwright end-to-end tests against the local stack:

```bash
pnpm test:e2e
```

The Playwright tests assume the frontend is available at <http://localhost:5173> and the API is available at <http://localhost:8000>.

The dashboard includes:

- a job submission form for `input_value`, `job_type`, and optional retry budget
- a selected-job panel that auto-refreshes until the job reaches `completed` or `failed`
- a recent-jobs list with status filtering and row selection

## Run on local Kubernetes with k3d

Use the following block as the complete end-to-end deployment flow from a Windows Terminal Ubuntu tab. It includes cluster cleanup, image build, cluster creation, image import, ingress installation, manifest apply, and verification commands.

```bash
k3d cluster delete distributed-jobs

docker compose build api celery_worker frontend

k3d cluster create distributed-jobs \
  --agents 1 \
  -p "8080:80@loadbalancer" \
  --k3s-arg "--disable=traefik@server:0"

k3d image import \
  distributed-job-processing-system-api:latest \
  distributed-job-processing-system-celery_worker:latest \
  distributed-job-processing-system-frontend:latest \
  -c distributed-jobs

kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=180s

kubectl apply -k infra/k8s/overlays/local

kubectl get pods -n dist-jobs
kubectl get ingress -n dist-jobs

curl http://localhost:8080/
curl http://localhost:8080/api/health
```

The sections below break out each subcommand from that full block and explain what it does.

Delete any existing local cluster first:

```bash
k3d cluster delete distributed-jobs
```

Build the local images:

```bash
docker compose build api celery_worker frontend
```

Create a local cluster:

```bash
k3d cluster create distributed-jobs --agents 1 -p "8080:80@loadbalancer" --k3s-arg "--disable=traefik@server:0"
```

The `@loadbalancer` suffix is a k3d node filter, not a name defined in this repository.
It targets the special `serverlb` container that k3d creates in front of the cluster,
so host traffic on `localhost:8080` reaches the cluster ingress entrypoint. Use this
filter for ingress-based access. Other filters such as `@server:0` or `@agent:0` target
specific cluster nodes directly instead.

The `--disable=traefik@server:0` argument turns off the default k3s Traefik ingress
controller so the separately installed `ingress-nginx` controller receives traffic on the
cluster entrypoint. If you created the cluster without this flag, delete and recreate it
before testing ingress.

Import the local images into that cluster:

```bash
k3d image import distributed-job-processing-system-api:latest \
  distributed-job-processing-system-celery_worker:latest \
  distributed-job-processing-system-frontend:latest \
  -c distributed-jobs
```

Install the ingress controller:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=180s
```

Apply the local overlay:

```bash
kubectl apply -k infra/k8s/overlays/local
```

Wait for the pods and inspect the ingress resources:

```bash
kubectl get pods -n dist-jobs
kubectl get ingress -n dist-jobs
```

Verify ingress routing:

```bash
curl http://localhost:8080/
curl http://localhost:8080/api/health
```

Without ingress, the deployments still run normally, but external access to each service
has to be exposed separately, often with different ports or port-forward sessions. With
ingress, Kubernetes `Ingress` resources define routing rules, and a single ingress
controller reads those rules and sends incoming HTTP traffic to the correct backend
service.

The frontend is exposed at <http://localhost:8080> and the API is exposed through the
same ingress entrypoint at <http://localhost:8080/api/health>.

The local Kubernetes base manifests live under `infra/k8s/base`, and the first local
overlay lives under `infra/k8s/overlays/local`.

## API usage

Health check:

```bash
curl http://localhost:8000/health
```

Submit a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"input_value":"hello-world","job_type":"echo"}'
```

Submit a job with a custom retry budget:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"input_value":"always-fail:demo","job_type":"uppercase","maximum_attempt_count":5}'
```

Example response:

```json
{
  "id": "6f98c765-4070-4d44-a576-5ee0f7f9af84",
  "input_value": "hello-world",
  "job_type": "echo",
  "status": "queued",
  "attempt_count": 0,
  "maximum_attempt_count": 3,
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

List jobs:

```bash
curl "http://localhost:8000/jobs?limit=10&offset=0"
```

List failed jobs only:

```bash
curl "http://localhost:8000/jobs?status=failed&limit=10&offset=0"
```

The job status flows through `queued`, `processing`, and `completed`, or `failed` if the worker raises an exception.

Retry behavior is deterministic for local verification:

- use `fail-once:<value>` to trigger one transient failure before the retry succeeds
- use `always-fail:<value>` to force terminal failure after the retry budget is exhausted

Supported job types:

- `echo` returns the input unchanged
- `reverse` reverses the input text before persisting the result
- `uppercase` uppercases the input text before persisting the result

API and worker logs include a correlation identifier:

- API requests use `X-Request-ID` if provided, or generate one automatically
- worker logs use `job:<job-id>` so a single job can be traced across retry attempts

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
