#!/usr/bin/env bash

# EKS APPLICATION DEPLOYMENT OVERVIEW
#
# Keep this ordered list current whenever this script gains, removes, or reorders steps.
# This script does not create the AWS foundation. Terraform must first provision the
# EKS cluster, managed nodes, networking, ECR repositories, and required IAM access.
#
# In order, this script:
# 1. Resolves the repository root, AWS account and region, EKS cluster, namespaces,
#    ECR registry, and immutable image tag (the current full Git SHA by default).
# 2. Creates temporary files for rendered Kubernetes and Argo CD manifests; tracked
#    templates remain account-neutral and the temporary files are deleted on exit.
# 3. Verifies that the required local commands are installed.
# 4. Refreshes kubeconfig for the existing EKS cluster and makes it the kubectl target.
# 5. Installs ingress-nginx and waits for its controller Deployment to become ready.
# 6. Installs or upgrades the pinned kube-prometheus-stack Helm release and waits for
#    its monitoring resources to become ready.
# 7. Installs or upgrades the pinned Argo CD Helm release, including its CRDs,
#    controllers, UI/API Service, repo server, Dex, dedicated Redis, RBAC, and config.
# 8. Creates the application namespace and, only when absent, generates and stores
#    PostgreSQL and Celery connection values in the application-secrets Secret.
# 9. Builds and publishes the API, Celery worker, and frontend images to ECR using the
#    immutable Git SHA tag, or reuses images already published for that commit.
# 10. Builds the EKS Kustomize overlay and replaces account and release placeholders
#     in temporary output with the selected ECR registry and image tag.
# 11. Deploys PostgreSQL first and waits for it before running database migrations.
# 12. Renders the one-off migration Job with the immutable API image, recreates the
#     Job with Kubernetes Service environment injection disabled, waits for completion,
#     and prints its logs if it fails or times out.
# 13. Directly applies the rendered EKS application and monitoring manifests, then
#     waits for PostgreSQL, RabbitMQ, API, worker, and frontend rollouts.
# 14. Renders and registers the manual-sync dist-jobs-eks Argo CD Application only
#     after the direct rollout is healthy; Argo CD does not take sync control yet.
# 15. Verifies that each application Deployment uses the expected immutable ECR image.
# 16. Reports application, monitoring, Argo CD, and ingress resources and prints the
#     ingress load balancer hostname.
#
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
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ARGOCD_RELEASE="${ARGOCD_RELEASE:-argocd}"
ARGOCD_CHART_VERSION="10.3.3"
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml"

# render account-specific values to a temporary file so tracked manifests stay unchanged
rendered_manifest="$(mktemp)"
rendered_migration_manifest="$(mktemp)"
rendered_argocd_application="$(mktemp)"
trap 'rm -f "$rendered_manifest" "$rendered_migration_manifest" "$rendered_argocd_application"' EXIT

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

# inject the exact immutable api image into the one-off migration job
render_migration_manifest() {
  sed \
    -e "s|distributed-job-processing-system-api:latest|${ECR_REGISTRY}/distributed-job-processing-system-api:${IMAGE_TAG}|" \
    "$repo_root/infra/k8s/base/database-migration-job.yaml" \
    >"$rendered_migration_manifest"

  if grep -Fq "distributed-job-processing-system-api:latest" "$rendered_migration_manifest"; then
    echo "rendered migration manifest still contains the local api image" >&2
    exit 1
  fi
}

# inject the selected ECR registry and immutable release into the EKS Application
render_argocd_application() {
  # sed reads the tracked template and replaces every deployment marker in its output
  # - deployment-registry becomes the authenticated account's ECR registry
  # - deployment-placeholder becomes the full Git SHA used by images and annotations
  # the redirected output is temporary, so the tracked template remains unchanged
  sed \
    -e "s|deployment-registry|${ECR_REGISTRY}|g" \
    -e "s|deployment-placeholder|${IMAGE_TAG}|g" \
    "$repo_root/infra/k8s/argocd/eks-application.yaml" \
    >"$rendered_argocd_application"

  if grep -Eq "deployment-(registry|placeholder)" "$rendered_argocd_application"; then
    echo "rendered EKS Application still contains deployment markers" >&2
    exit 1
  fi
}

# recreate the fixed-name job so its immutable pod template uses the current image
run_database_migration() {
  kubectl delete job database-migration \
    --namespace "$NAMESPACE" \
    --ignore-not-found \
    --wait=true

  kubectl apply \
    --namespace "$NAMESPACE" \
    --filename "$rendered_migration_manifest"

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

# install the GitOps control plane without registering this project's Application yet
# Helm chart 10.3.3 creates:
# - CRDs: applications, applicationsets, and appprojects
# - Services: server (UI/API), repo-server, applicationset-controller, Dex, and Redis
# - Deployments: server, repo-server, applicationset-controller, notifications, Dex, and Redis
# - StatefulSet: application-controller, which compares desired and live state
# - supporting resources: ServiceAccounts, RBAC, ConfigMaps, Secrets, NetworkPolicies,
#   and the Redis secret-initialization Job
# Important: this chart installs a dedicated Redis instance for Argo CD's internal
# caching and coordination; it is not part of the job-processing application stack
echo "installing Argo CD"
helm upgrade --install "$ARGOCD_RELEASE" oci://ghcr.io/argoproj/argo-helm/argo-cd \
  --namespace "$ARGOCD_NAMESPACE" \
  --create-namespace \
  --version "$ARGOCD_CHART_VERSION" \
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

# apply only the resources required by the migration, then wait for postgres
echo "preparing database migration"
kubectl apply \
  --namespace "$NAMESPACE" \
  --filename "$repo_root/infra/k8s/base/postgres-deployment.yaml" \
  --filename "$repo_root/infra/k8s/base/postgres-service.yaml"
kubectl rollout status deployment/postgres --namespace "$NAMESPACE" --timeout=300s

echo "running database migration"
render_migration_manifest
run_database_migration

echo "applying rendered EKS overlay"
kubectl apply -f "$rendered_manifest"

echo "waiting for application deployments"
for deployment in postgres rabbitmq api celery-worker frontend; do
  kubectl rollout status "deployment/${deployment}" --namespace "$NAMESPACE" --timeout=300s
done

# register the desired state only after the direct rollout is healthy
echo "registering EKS Argo CD application"
render_argocd_application
kubectl apply --filename "$rendered_argocd_application"
kubectl get application dist-jobs-eks --namespace "$ARGOCD_NAMESPACE"

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

echo "Argo CD control plane deployed"
helm status "$ARGOCD_RELEASE" --namespace "$ARGOCD_NAMESPACE"
kubectl get pods,services --namespace "$ARGOCD_NAMESPACE"

echo "ingress endpoint"
kubectl get service ingress-nginx-controller \
  --namespace ingress-nginx \
  --output jsonpath='{.status.loadBalancer.ingress[0].hostname}'
echo