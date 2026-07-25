#!/usr/bin/env bash

set -euo pipefail

AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short=12 HEAD)}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
CLUSTER_NAME="${CLUSTER_NAME:-dist-jobs}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
overlay_file="$repo_root/infra/k8s/overlays/eks/kustomization.yaml"

api_repo="distributed-job-processing-system-api"
worker_repo="distributed-job-processing-system-celery-worker"
frontend_repo="distributed-job-processing-system-frontend"

ensure_repo() {
  local repo_name="$1"

  if aws ecr describe-repositories --repository-names "$repo_name" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "repository exists: $repo_name"
    return
  fi

  echo "creating repository: $repo_name"
  aws ecr create-repository --repository-name "$repo_name" --region "$AWS_REGION" >/dev/null
}

build_tag_push() {
  local source_image="$1"
  local target_repo="$2"

  local target_image="${ECR_REGISTRY}/${target_repo}:${IMAGE_TAG}"

  echo "tagging ${source_image} as ${target_image}"
  docker tag "$source_image" "$target_image"

  echo "pushing ${target_image}"
  docker push "$target_image"
}

echo "ensuring ECR repositories exist"
ensure_repo "$api_repo"
ensure_repo "$worker_repo"
ensure_repo "$frontend_repo"

echo "authenticating docker to ECR"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "building local images for cluster ${CLUSTER_NAME} with docker compose"
cd "$repo_root"
docker compose build api celery_worker frontend

build_tag_push "distributed-job-processing-system-api:latest" "$api_repo"
build_tag_push "distributed-job-processing-system-celery_worker:latest" "$worker_repo"
build_tag_push "distributed-job-processing-system-frontend:latest" "$frontend_repo"

echo "updating EKS overlay image references in ${overlay_file}"
sed -i \
  -e "s|newName: .*distributed-job-processing-system-api|newName: ${ECR_REGISTRY}/${api_repo}|" \
  -e "s|newName: .*distributed-job-processing-system-celery-worker|newName: ${ECR_REGISTRY}/${worker_repo}|" \
  -e "s|newName: .*distributed-job-processing-system-frontend|newName: ${ECR_REGISTRY}/${frontend_repo}|" \
  -e "s|newTag: .*|newTag: ${IMAGE_TAG}|g" \
  "$overlay_file"

echo "done"
echo "published immutable image tag: ${IMAGE_TAG}"
echo "render check: kubectl kustomize infra/k8s/overlays/eks"
