#!/usr/bin/env bash

# EKS recreation changes its API endpoint; this script refreshes kubeconfig below.
# For manual kubectl or helm access after redeployment, rerun:
# aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

# derive the registry from the authenticated AWS account instead of storing an account ID in Git
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$repo_root" rev-parse HEAD)}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
CLUSTER_NAME="${CLUSTER_NAME:-dist-jobs}"
NAMESPACE="${NAMESPACE:-dist-jobs}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
MONITORING_RELEASE="${MONITORING_RELEASE:-monitoring}"
MONITORING_CHART_VERSION="87.21.0"
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml"

# render account-specific values to a temporary file so tracked manifests stay unchanged
rendered_manifest="$(mktemp)"
trap 'rm -f "$rendered_manifest"' EXIT

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

# render Kustomize first, then replace only the explicit deployment placeholders
render_deployment_manifest() {
  kubectl kustomize "$repo_root/infra/k8s/overlays/eks" |
    sed \
      -e "s|000000000000.dkr.ecr.us-east-1.amazonaws.com/distributed-job-processing-system-api:deployment-placeholder|${ECR_REGISTRY}/distributed-job-processing-system-api:${IMAGE_TAG}|g" \
      -e "s|000000000000.dkr.ecr.us-east-1.amazonaws.com/distributed-job-processing-system-celery-worker:deployment-placeholder|${ECR_REGISTRY}/distributed-job-processing-system-celery-worker:${IMAGE_TAG}|g" \
      -e "s|000000000000.dkr.ecr.us-east-1.amazonaws.com/distributed-job-processing-system-frontend:deployment-placeholder|${ECR_REGISTRY}/distributed-job-processing-system-frontend:${IMAGE_TAG}|g" \
      -e "s|distributed-jobs.dev/source-revision: deployment-placeholder|distributed-jobs.dev/source-revision: ${IMAGE_TAG}|g" \
      >"$rendered_manifest"

  # fail before kubectl apply if a template value was not replaced
  if grep -Fq "deployment-placeholder" "$rendered_manifest"; then
    echo "rendered EKS manifest still contains deployment placeholders" >&2
    exit 1
  fi
}

# confirm Kubernetes accepted the exact immutable image URI for each application workload
verify_deployment_image() {
  local deployment_name="$1"
  local container_name="$2"
  local expected_image="$3"
  local deployed_image

  deployed_image="$(
    kubectl get deployment "$deployment_name" \
      --namespace "$NAMESPACE" \
      --output "jsonpath={.spec.template.spec.containers[?(@.name=='${container_name}')].image}"
  )"

  if [[ "$deployed_image" != "$expected_image" ]]; then
    echo "deployment ${deployment_name} uses ${deployed_image}; expected ${expected_image}" >&2
    exit 1
  fi

  echo "verified deployment ${deployment_name} image: ${deployed_image}"
}

require_command aws
require_command helm
require_command kubectl
require_command openssl
require_command bash
require_command grep
require_command sed

export AWS_ACCOUNT_ID AWS_REGION IMAGE_TAG

echo "updating kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

echo "installing ingress-nginx"
kubectl apply -f "$INGRESS_NGINX_MANIFEST"
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=300s

echo "installing monitoring stack"
helm upgrade --install "$MONITORING_RELEASE" oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace "$MONITORING_NAMESPACE" \
  --create-namespace \
  --version "$MONITORING_CHART_VERSION" \
  --values "$repo_root/infra/k8s/overlays/eks/monitoring/eks-monitoring-values.yaml" \
  --atomic \
  --wait \
  --timeout 10m

echo "creating namespace ${NAMESPACE}"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "creating application secret when absent"
create_application_secret

echo "publishing application images to ECR"
bash "$repo_root/infra/k8s/overlays/eks/publish-images.sh"

echo "rendering EKS overlay for commit ${IMAGE_TAG}"
render_deployment_manifest

echo "applying rendered EKS overlay"
kubectl apply -f "$rendered_manifest"

echo "waiting for application deployments"
for deployment in postgres rabbitmq api celery-worker frontend; do
  kubectl rollout status "deployment/${deployment}" --namespace "$NAMESPACE" --timeout=300s
done

echo "verifying immutable application images"
verify_deployment_image "api" "api" "${ECR_REGISTRY}/distributed-job-processing-system-api:${IMAGE_TAG}"
verify_deployment_image "celery-worker" "celery-worker" "${ECR_REGISTRY}/distributed-job-processing-system-celery-worker:${IMAGE_TAG}"
verify_deployment_image "frontend" "frontend" "${ECR_REGISTRY}/distributed-job-processing-system-frontend:${IMAGE_TAG}"

echo "application stack deployed"
echo "deployed immutable image tag: ${IMAGE_TAG}"
kubectl get pods,services,ingress --namespace "$NAMESPACE"

echo "monitoring stack deployed"
helm status "$MONITORING_RELEASE" --namespace "$MONITORING_NAMESPACE"
kubectl get pods,services --namespace "$MONITORING_NAMESPACE"

echo "ingress endpoint"
kubectl get service ingress-nginx-controller \
  --namespace ingress-nginx \
  --output jsonpath='{.status.loadBalancer.ingress[0].hostname}'
echo