#!/usr/bin/env bash

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-distributed-jobs}"
NAMESPACE="${NAMESPACE:-dist-jobs}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
MONITORING_RELEASE="${MONITORING_RELEASE:-monitoring}"
MONITORING_CHART_VERSION="87.21.0"
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

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

echo "recreating k3d cluster ${CLUSTER_NAME}"
k3d cluster delete "$CLUSTER_NAME" || true
k3d cluster create "$CLUSTER_NAME" \
  --agents 1 \
  -p "8080:80@loadbalancer" \
  --k3s-arg "--disable=traefik@server:0"

echo "building application images"
docker compose --project-directory "$repo_root" build api celery_worker frontend

echo "importing application images"
k3d image import \
  distributed-job-processing-system-api:latest \
  distributed-job-processing-system-celery_worker:latest \
  distributed-job-processing-system-frontend:latest \
  --cluster "$CLUSTER_NAME"

echo "installing ingress-nginx"
kubectl apply -f "$INGRESS_NGINX_MANIFEST"
kubectl rollout status deployment/ingress-nginx-controller --namespace ingress-nginx --timeout=180s

echo "installing monitoring stack"
helm upgrade --install "$MONITORING_RELEASE" oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace "$MONITORING_NAMESPACE" \
  --create-namespace \
  --version "$MONITORING_CHART_VERSION" \
  --values "$repo_root/infra/k8s/overlays/local/monitoring-values.yaml" \
  --atomic \
  --wait \
  --timeout 10m

echo "applying local application overlay"
kubectl apply -k "$repo_root/infra/k8s/overlays/local"

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