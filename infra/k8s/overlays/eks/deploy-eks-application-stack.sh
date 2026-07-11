#!/usr/bin/env bash

set -euo pipefail

AWS_REGION=us-east-1
CLUSTER_NAME=dist-jobs
NAMESPACE=dist-jobs
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

create_application_secret() {
  if kubectl get secret application-secrets --namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "application secret already exists; preserving its current values"
    return
  fi

  local postgres_password
  postgres_password="$(openssl rand -hex 24 | cut -c 1-24)"

  kubectl create secret generic application-secrets \
    --namespace "$NAMESPACE" \
    --from-literal=POSTGRES_DB=jobs \
    --from-literal=POSTGRES_USER=postgres \
    --from-literal="POSTGRES_PASSWORD=${postgres_password}" \
    --from-literal="DATABASE_URL=postgresql+psycopg://postgres:${postgres_password}@postgres:5432/jobs" \
    --from-literal=CELERY_BROKER_URL='amqp://guest:guest@rabbitmq:5672//'
}

require_command aws
require_command kubectl
require_command openssl
require_command bash

echo "updating kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

echo "installing ingress-nginx"
kubectl apply -f "$INGRESS_NGINX_MANIFEST"
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=300s

echo "creating namespace ${NAMESPACE}"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "creating application secret when absent"
create_application_secret

echo "publishing application images to ECR"
bash "$repo_root/infra/k8s/overlays/eks/publish-images.sh"

echo "applying EKS overlay"
kubectl apply -k "$repo_root/infra/k8s/overlays/eks"

echo "waiting for application deployments"
for deployment in postgres rabbitmq api celery-worker frontend; do
  kubectl rollout status "deployment/${deployment}" --namespace "$NAMESPACE" --timeout=300s
done

echo "application stack deployed"
kubectl get pods,services,ingress --namespace "$NAMESPACE"

echo "ingress endpoint"
kubectl get service ingress-nginx-controller \
  --namespace ingress-nginx \
  --output jsonpath='{.status.loadBalancer.ingress[0].hostname}'
echo