#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$repo_root" rev-parse HEAD)}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
CLUSTER_NAME="${CLUSTER_NAME:-dist-jobs}"

api_repo="distributed-job-processing-system-api"
worker_repo="distributed-job-processing-system-celery-worker"
frontend_repo="distributed-job-processing-system-frontend"

# require a full commit SHA so every ECR tag maps to one exact source revision
if [[ ! "$IMAGE_TAG" =~ ^[0-9a-f]{40}$ ]]; then
  echo "IMAGE_TAG must be a full 40-character lowercase Git commit SHA" >&2
  exit 1
fi

ensure_repo() {
  local repo_name="$1"

  if aws ecr describe-repositories --repository-names "$repo_name" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "repository exists: $repo_name"
    # preserve immutability for repositories created manually before Terraform adoption
    aws ecr put-image-tag-mutability \
      --repository-name "$repo_name" \
      --image-tag-mutability IMMUTABLE \
      --region "$AWS_REGION" >/dev/null
    return
  fi

  echo "creating repository: $repo_name"
  aws ecr create-repository \
    --repository-name "$repo_name" \
    --image-tag-mutability IMMUTABLE \
    --region "$AWS_REGION" >/dev/null
}

image_exists() {
  local repo_name="$1"

  aws ecr describe-images \
    --repository-name "$repo_name" \
    --image-ids "imageTag=${IMAGE_TAG}" \
    --region "$AWS_REGION" >/dev/null 2>&1
}

# immutable repositories reject a second push to the same tag, so reuse published commits
build_tag_push() {
  local source_image="$1"
  local target_repo="$2"

  local target_image="${ECR_REGISTRY}/${target_repo}:${IMAGE_TAG}"

  if image_exists "$target_repo"; then
    echo "reusing existing immutable image ${target_image}"
    return
  fi

  echo "tagging ${source_image} as ${target_image}"
  docker tag "$source_image" "$target_image"

  echo "pushing ${target_image}"
  docker push "$target_image"
}

echo "ensuring ECR repositories exist"
ensure_repo "$api_repo"
ensure_repo "$worker_repo"
ensure_repo "$frontend_repo"

# skip Docker entirely during rollback when all artifacts for the selected commit already exist
if image_exists "$api_repo" && image_exists "$worker_repo" && image_exists "$frontend_repo"; then
  echo "all images already exist for commit ${IMAGE_TAG}; skipping build and push"
else
  echo "authenticating docker to ECR"
  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

  echo "building local images for cluster ${CLUSTER_NAME} with docker compose"
  cd "$repo_root"
  docker compose --project-name distributed-job-processing-system build api celery_worker frontend

  build_tag_push "distributed-job-processing-system-api:latest" "$api_repo"
  build_tag_push "distributed-job-processing-system-celery_worker:latest" "$worker_repo"
  build_tag_push "distributed-job-processing-system-frontend:latest" "$frontend_repo"
fi

echo "done"
echo "immutable image tag ready: ${IMAGE_TAG}"
