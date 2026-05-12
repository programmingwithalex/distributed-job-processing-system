# Local Kubernetes with k3d

This directory contains the first local Kubernetes deployment for the project.

## Layout

- `base/` is the shared baseline manifest set for the application stack
- `overlays/local/` adds local-only values on top of that shared baseline
- `base/` is named that way because the same common manifests can later be reused by `dev`, `qa`, and `prod` overlays

## Key ideas

- `k3d` runs a lightweight local Kubernetes cluster on top of Docker
- a cluster is the whole Kubernetes system; a node is one machine inside that cluster where pods actually run
- in `k3d`, each node is implemented as a Docker container
- `--agents 1` adds one worker node to the cluster in addition to the default control-plane node
- `kustomize` is a manifest composition tool; it lets us reuse a shared manifest set and layer environment-specific changes on top
- `base/kustomization.yaml` lists the common resources that define the application stack
- `overlays/local/kustomization.yaml` says to reuse `../../base`, add the local secret, and stamp the namespace onto the rendered resources
- `overlays/local/secret.yaml` provides the concrete secret values for local development

## Why the image build step exists

- Kubernetes does not build images from Dockerfiles or Compose files
- the manifests reference prebuilt images such as `distributed-job-processing-system-api:latest`
- `docker compose build api celery_worker frontend` creates those images locally before we import them into the `k3d` cluster
- `k3d image import ...` copies the local images into the cluster so the Kubernetes nodes can run them

## Why the image names are long

- Docker Compose derives image names from the Compose project name plus the service name when no explicit `image:` field is set
- in this repo, the project name defaults to the folder name `distributed-job-processing-system`
- the service names come from `docker-compose.yml`, so names such as `distributed-job-processing-system-api:latest` are generated automatically

## First local workflow

- build the application images:

```bash
docker compose build api celery_worker frontend
```

- create the cluster:

```bash
k3d cluster create distributed-jobs --agents 1
```

- import the images into the cluster:

```bash
k3d image import distributed-job-processing-system-api:latest distributed-job-processing-system-celery_worker:latest distributed-job-processing-system-frontend:latest -c distributed-jobs
```

- apply the local overlay:

```bash
kubectl apply -k infra/k8s/overlays/local
```

- check pod state:

```bash
kubectl get pods -n distributed-job-processing-system
```

- wait until the pods settle into `Running` before testing the app; the first startup can take a bit while containers initialize

- port-forward the frontend and api:

```bash
kubectl port-forward -n distributed-job-processing-system svc/frontend 5173:5173
kubectl port-forward -n distributed-job-processing-system svc/api 8000:8000
```

- run those port-forward commands in separate terminals because each command stays attached to its shell session
- in PowerShell, prefer `curl.exe` or `Invoke-RestMethod` over `curl` to avoid the `Invoke-WebRequest` parsing prompt

- quick health check:

```bash
curl.exe http://localhost:8000/health
```

## Helpful debugging commands

- inspect pods:

```bash
kubectl get pods -n distributed-job-processing-system
```

- inspect one pod in detail:

```bash
kubectl describe pod <pod-name> -n distributed-job-processing-system
```

- read logs from one pod:

```bash
kubectl logs <pod-name> -n distributed-job-processing-system
```

## Applying manifest updates

- if you update a deployment or service yaml file, reapply the local overlay:

```bash
kubectl apply -k infra/k8s/overlays/local
```

- if you changed a deployment and want new pods to restart immediately:

```bash
kubectl rollout restart deployment/<deployment-name> -n distributed-job-processing-system
```

- examples:

```bash
kubectl rollout restart deployment/api -n distributed-job-processing-system
kubectl rollout restart deployment/celery-worker -n distributed-job-processing-system
kubectl rollout restart deployment/frontend -n distributed-job-processing-system
kubectl rollout restart deployment/postgres -n distributed-job-processing-system
kubectl rollout restart deployment/rabbitmq -n distributed-job-processing-system
```

- if you only changed a service file, `kubectl apply -k ...` is usually enough because services do not create pods