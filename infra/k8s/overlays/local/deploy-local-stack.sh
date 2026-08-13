#!/usr/bin/env bash

set -euo pipefail

# allow callers to override names while keeping predictable local defaults
CLUSTER_NAME="${CLUSTER_NAME:-distributed-jobs}"
NAMESPACE="${NAMESPACE:-dist-jobs}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
MONITORING_RELEASE="${MONITORING_RELEASE:-monitoring}"
MONITORING_CHART_VERSION="87.21.0"
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml"

# resolve every relative path from the repository root, regardless of the caller's directory
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

# fail before changing the cluster when a required local tool is unavailable
require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

require_command docker
require_command helm
require_command k3d
require_command kubectl

# recreate the fixed-name job so its immutable pod template uses the current image
run_database_migration() {
  kubectl delete job database-migration \
    --namespace "$NAMESPACE" \
    --ignore-not-found \
    --wait=true

  kubectl apply \
    --namespace "$NAMESPACE" \
    --filename "$repo_root/infra/k8s/base/database-migration-job.yaml"

  # print migration logs when the job fails or exceeds its five-minute budget
  if ! kubectl wait \
    --namespace "$NAMESPACE" \
    --for=condition=complete \
    job/database-migration \
    --timeout=300s; then
    kubectl logs job/database-migration --namespace "$NAMESPACE" || true
    exit 1
  fi
}

# start from a clean cluster so stale images and Kubernetes resources cannot affect the test
echo "recreating k3d cluster ${CLUSTER_NAME}"
k3d cluster delete "$CLUSTER_NAME" || true
# expose one ingress entrypoint and reserve it for ingress-nginx instead of Traefik
k3d cluster create "$CLUSTER_NAME" \
  --agents 1 \
  -p "8080:80@loadbalancer" \
  --k3s-arg "--disable=traefik@server:0"

# build the current working tree, including uncommitted application changes
echo "building application images"
docker compose --project-directory "$repo_root" build api celery_worker frontend

# copy local images into k3d's container runtime so deployments do not pull stale registry images
echo "importing application images"
k3d image import \
  distributed-job-processing-system-api:latest \
  distributed-job-processing-system-celery_worker:latest \
  distributed-job-processing-system-frontend:latest \
  --cluster "$CLUSTER_NAME"

# install the controller that routes localhost:8080 traffic using the application's Ingress rules
echo "installing ingress-nginx"
kubectl apply -f "$INGRESS_NGINX_MANIFEST"
kubectl rollout status deployment/ingress-nginx-controller --namespace ingress-nginx --timeout=180s

# install Prometheus, Grafana, and Alertmanager before applying their custom monitoring resources
echo "installing monitoring stack"
helm upgrade --install "$MONITORING_RELEASE" oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace "$MONITORING_NAMESPACE" \
  --create-namespace \
  --version "$MONITORING_CHART_VERSION" \
  --values "$repo_root/infra/k8s/overlays/local/local-monitoring-values.yaml" \
  --atomic \
  --wait \
  --timeout 10m

# apply only the resources required by the migration, then wait for postgres
echo "preparing database migration"
kubectl apply --filename "$repo_root/infra/k8s/base/namespace.yaml"
kubectl apply \
  --namespace "$NAMESPACE" \
  --filename "$repo_root/infra/k8s/overlays/local/secret.yaml" \
  --filename "$repo_root/infra/k8s/base/postgres-deployment.yaml" \
  --filename "$repo_root/infra/k8s/base/postgres-service.yaml"
kubectl rollout status deployment/postgres --namespace "$NAMESPACE" --timeout=300s

echo "running database migration"
run_database_migration

# create the application namespace, configuration, workloads, services, ingress, and monitors
echo "applying local application overlay"
kubectl apply -k "$repo_root/infra/k8s/overlays/local"

# wait for every application workload before reporting the stack as usable
echo "waiting for application deployments"
for deployment in postgres rabbitmq api celery-worker frontend; do
  kubectl rollout status "deployment/${deployment}" --namespace "$NAMESPACE" --timeout=300s
done

echo "local application and monitoring stacks deployed"
kubectl get pods --namespace "$NAMESPACE"
kubectl get pods --namespace "$MONITORING_NAMESPACE"

cat <<EOF

Access the application at http://localhost:8080

Access Alertmanager in a separate terminal:
  kubectl port-forward --namespace ${MONITORING_NAMESPACE} service/${MONITORING_RELEASE}-kube-prometheus-alertmanager 9093:9093
  open http://localhost:9093
EOF