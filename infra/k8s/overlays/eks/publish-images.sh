#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 <aws-account-id> <aws-region> [image-tag]"
  echo "example: $0 123456789012 us-east-1 v1"
  exit 1
fi

aws_account_id="$1"
aws_region="$2"
image_tag="${3:-latest}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
overlay_file="$repo_root/infra/k8s/overlays/eks/kustomization.yaml"
ecr_registry="${aws_account_id}.dkr.ecr.${aws_region}.amazonaws.com"

api_repo="distributed-job-processing-system-api"
worker_repo="distributed-job-processing-system-celery-worker"
frontend_repo="distributed-job-processing-system-frontend"

ensure_repo() {
  local repo_name="$1"

  if aws ecr describe-repositories --repository-names "$repo_name" --region "$aws_region" >/dev/null 2>&1; then
    echo "repository exists: $repo_name"
    return
  fi

  echo "creating repository: $repo_name"
  aws ecr create-repository --repository-name "$repo_name" --region "$aws_region" >/dev/null
}

build_tag_push() {
  local source_image="$1"
  local target_repo="$2"

  local target_image="${ecr_registry}/${target_repo}:${image_tag}"

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
aws ecr get-login-password --region "$aws_region" | docker login --username AWS --password-stdin "$ecr_registry"

echo "building local images with docker compose"
cd "$repo_root"
docker compose build api celery_worker frontend

build_tag_push "distributed-job-processing-system-api:latest" "$api_repo"
build_tag_push "distributed-job-processing-system-celery_worker:latest" "$worker_repo"
build_tag_push "distributed-job-processing-system-frontend:latest" "$frontend_repo"

echo "updating EKS overlay image references in ${overlay_file}"
sed -i \
  -e "s|newName: .*distributed-job-processing-system-api|newName: ${ecr_registry}/${api_repo}|" \
  -e "s|newName: .*distributed-job-processing-system-celery-worker|newName: ${ecr_registry}/${worker_repo}|" \
  -e "s|newName: .*distributed-job-processing-system-frontend|newName: ${ecr_registry}/${frontend_repo}|" \
  -e "s|newTag: .*|newTag: ${image_tag}|g" \
  "$overlay_file"

echo "done"
echo "render check: kubectl kustomize infra/k8s/overlays/eks"
