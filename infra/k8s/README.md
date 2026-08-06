# Local Kubernetes with k3d

This directory contains the first local Kubernetes deployment for the project.

## Layout

- `base/` is the shared baseline manifest set for the application stack
- `overlays/local/` adds local-only values on top of that shared baseline
- `monitoring/` contains the shared API `ServiceMonitor`, alert rules, and Grafana dashboard
- `base/` is named that way because the same common manifests can later be reused by `dev`, `qa`, and `prod` overlays

## Key ideas

- `k3d` runs a lightweight local Kubernetes cluster on top of Docker
- a cluster is the whole Kubernetes system; a node is one machine inside that cluster where pods actually run
- in `k3d`, each node is implemented as a Docker container
- `--agents 1` adds one worker node to the cluster in addition to the default control-plane node
- `overlays/local/secret.yaml` provides the concrete secret values for local development
- `overlays/local/monitoring-values.yaml` constrains the local Prometheus, Grafana, and Alertmanager resources

## Kustomize structure

- `kustomize` is a manifest composition tool; it lets us reuse a shared manifest set and layer environment-specific changes on top
- each `kustomization.yaml` file acts like a grouping and assembly point for Kubernetes resources; it tells `kustomize` which manifests to include and what changes to apply before anything is sent to the cluster
- `base/kustomization.yaml` lists the common resources that define the application stack
- `overlays/local/kustomization.yaml` lives in a subdirectory because that folder represents one environment-specific layer; it says to reuse `../../base`, add the local secret, and stamp the namespace onto the rendered resources
- overlay `kustomization.yaml` files usually do two jobs at once: they point back to the shared base manifests and they declare the overrides for that environment, such as secrets, image replacements, patches, or namespace settings
- the subdirectory layout matters because it makes the intent clear: `base/` holds the reusable templates, while folders such as `overlays/local/` or `overlays/eks/` hold the `kustomization.yaml` file that explains how to customize that base for one target environment

## Why the image build step exists

- Kubernetes does not build images from Dockerfiles or Compose files
- the manifests reference prebuilt images such as `distributed-job-processing-system-api:latest`
- `docker compose build api celery_worker frontend` creates those images locally before we import them into the `k3d` cluster
- `k3d image import ...` copies the local images into the cluster so the Kubernetes nodes can run them

## Why the image names are long

- Docker Compose derives image names from the Compose project name plus the service name when no explicit `image:` field is set
- in this repo, the project name defaults to the folder name `distributed-job-processing-system`
- the service names come from `docker-compose.yml`, so names such as `distributed-job-processing-system-api:latest` are generated automatically

## Local Application and Monitoring Workflow

The preferred local deployment recreates the k3d cluster, deploys ingress-nginx and the pinned `kube-prometheus-stack` chart, then applies the application and shared monitoring manifests:

```bash
bash infra/k8s/overlays/local/deploy-local-stack.sh
```

The helper requires Docker, k3d, kubectl, and Helm. It installs the monitoring stack into the `monitoring` namespace and the application plus its `ServiceMonitor`, alert rules, and dashboard ConfigMap into `dist-jobs`.

For local Grafana access after the helper completes:

```bash
kubectl port-forward --namespace monitoring service/monitoring-grafana 3000:80
```

Open <http://localhost:3000> and sign in with username `admin`. Retrieve the generated password with:

```bash
kubectl get secret monitoring-grafana --namespace monitoring \
  --output jsonpath='{.data.admin-password}' | base64 --decode
echo
```

For local Alertmanager access, use a second terminal:

```bash
kubectl port-forward --namespace monitoring service/monitoring-kube-prometheus-alertmanager 9093:9093
```

Open <http://localhost:9093> to inspect active alerts and their routing state.

### Validate an API availability alert locally

The `APIAllTargetsDown` rule normally waits five minutes before firing. To demonstrate the complete alert path locally without waiting five minutes, leave the Alertmanager port-forward running, then scale the API to zero:

```bash
kubectl scale deployment/api --namespace dist-jobs --replicas=0
```

Temporarily shorten only the live rule evaluation window to 30 seconds. This does not change the Git-managed manifest:

```bash
kubectl patch prometheusrule api --namespace dist-jobs \
  --type=json \
  --patch='[{"op":"replace","path":"/spec/groups/0/rules/0/for","value":"30s"}]'
```

After Prometheus completes a scrape and rule-evaluation cycle, refresh <http://localhost:9093>. The `APIAllTargetsDown` alert should appear with `severity="critical"` and `job="api"`.

Restore the five-minute duration and the API deployment after the demonstration:

```bash
kubectl patch prometheusrule api --namespace dist-jobs \
  --type=json \
  --patch='[{"op":"replace","path":"/spec/groups/0/rules/0/for","value":"5m"}]'

kubectl scale deployment/api --namespace dist-jobs --replicas=1
kubectl rollout status deployment/api --namespace dist-jobs --timeout=300s
```

### Manual deployment

Use the following block when you want the same flow as individual commands. It includes cluster cleanup, image build, cluster creation, image import, ingress installation, monitoring installation, manifest apply, and verification commands:

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

helm upgrade --install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version 87.21.0 \
  --values infra/k8s/overlays/local/monitoring-values.yaml \
  --atomic \
  --wait \
  --timeout 10m

kubectl apply -k infra/k8s/overlays/local

kubectl get pods -n dist-jobs
kubectl get pods -n monitoring
kubectl get ingress -n dist-jobs

curl http://localhost:8080/
curl http://localhost:8080/api/health
```

- the steps below break out each subcommand from that full block and explain what it does.

### Create the cluster

- delete any existing local cluster first:

```bash
k3d cluster delete distributed-jobs
```

- build the application images:

```bash
docker compose build api celery_worker frontend
```

- create the cluster:

```bash
k3d cluster create distributed-jobs --agents 1 -p "8080:80@loadbalancer" --k3s-arg "--disable=traefik@server:0"
```

- `-p "8080:80@loadbalancer"` publishes host port `8080` to port `80` on the special `k3d` load balancer container
- `loadbalancer` is the target keyword because ingress traffic should enter the cluster through that shared entrypoint, not directly through an individual node
- without that mapping, an ingress controller can still run inside the cluster, but `http://localhost:8080` will not reach it from your machine
- `--disable=traefik@server:0` turns off the default k3s Traefik ingress controller so `ingress-nginx` can own the cluster entrypoint on port `80`
- if you created the cluster without that flag, delete and recreate the cluster before testing ingress, because k3s startup arguments are fixed at cluster creation time

- import the images into the cluster:

```bash
k3d image import distributed-job-processing-system-api:latest distributed-job-processing-system-celery_worker:latest distributed-job-processing-system-frontend:latest -c distributed-jobs
```

### Install platform services

- install the ingress-nginx controller:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=180s
```

- install the local monitoring stack before applying the local overlay, because the overlay contains Prometheus Operator custom resources:

```bash
helm upgrade --install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version 87.21.0 \
  --values infra/k8s/overlays/local/monitoring-values.yaml \
  --atomic \
  --wait \
  --timeout 10m
```

### Deploy the application

- apply the local overlay:

```bash
kubectl apply -k infra/k8s/overlays/local
```

- the local overlay applies the shared API monitoring resources from `infra/k8s/monitoring/`. Prometheus discovers the API through the `ServiceMonitor`; Grafana discovers the dashboard ConfigMap through its dashboard sidecar.

- the `deploy.yaml` file is the official upstream ingress-nginx install manifest published from the Kubernetes ingress-nginx repository
- it creates the controller deployment plus the supporting namespace, RBAC, admission webhook, service accounts, and related resources needed to run ingress-nginx in the cluster

### Verify the deployment

- inspect the ingress resources:

```bash
kubectl get ingress -n dist-jobs
```

- check pod state:

```bash
kubectl get pods -n dist-jobs
kubectl get pods -n monitoring
```

- wait until the pods settle into `Running` before testing the app; the first startup can take a bit while containers initialize

- in PowerShell, prefer `curl.exe` or `Invoke-RestMethod` over `curl` to avoid the `Invoke-WebRequest` parsing prompt

- ingress-based checks:

```bash
curl.exe http://localhost:8080/
curl.exe http://localhost:8080/api/health
```

## Why ingress-nginx exists

- Without ingress, the deployments still run normally, but external access to each service has to be exposed separately, often with different ports or port-forward sessions. With ingress, Kubernetes `Ingress` resources define routing rules, and a single ingress controller reads those rules and sends incoming HTTP traffic to the correct backend service.
- Kubernetes services are internal service-discovery objects; by themselves they do not give you one clean HTTP entrypoint for multiple apps
- an ingress controller watches `Ingress` resources and turns host/path rules into actual reverse-proxy behavior
- `ingress-nginx` is a widely used controller that accepts incoming HTTP traffic and routes it to the correct service based on rules such as hostnames or URL paths
- this solves the problem of exposing multiple services through one stable entrypoint instead of juggling separate `port-forward` sessions for each service
- for this project, that gives us a more realistic platform shape: host traffic enters through the k3d load balancer, reaches nginx ingress, then gets routed to the frontend or api service
- in this repo, the frontend ingress handles `/`, while the api ingress handles `/api/...` and strips the `/api` prefix before forwarding to the FastAPI service

## Helpful debugging commands

- inspect pods:

```bash
kubectl get pods -n dist-jobs
```

- inspect one pod in detail:

```bash
kubectl describe pod <pod-name> -n dist-jobs
```

- read logs from one pod:

```bash
kubectl logs <pod-name> -n dist-jobs
```

## Applying manifest updates

- if you update a deployment or service yaml file, reapply the local overlay:

```bash
kubectl apply -k infra/k8s/overlays/local
```

- if you changed a deployment and want new pods to restart immediately:

```bash
kubectl rollout restart deployment/<deployment-name> -n dist-jobs
```

- examples:

```bash
kubectl rollout restart deployment/api -n dist-jobs
kubectl rollout restart deployment/celery-worker -n dist-jobs
kubectl rollout restart deployment/frontend -n dist-jobs
kubectl rollout restart deployment/postgres -n dist-jobs
kubectl rollout restart deployment/rabbitmq -n dist-jobs
```

- if you only changed a service file, `kubectl apply -k ...` is usually enough because services do not create pods
