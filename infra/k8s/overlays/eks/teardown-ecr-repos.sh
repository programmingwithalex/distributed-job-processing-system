#!/usr/bin/env bash

# **************************************************** #
# ** usage ** #

# AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
# bash infra/k8s/overlays/eks/teardown-ecr-repos.sh "$AWS_ACCOUNT_ID" us-east-1

# **************************************************** #

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <aws-account-id> <aws-region>"
  echo "example: $0 123456789012 us-east-1"
  exit 1
fi

aws_account_id="$1"
aws_region="$2"

api_repo="distributed-job-processing-system-api"
worker_repo="distributed-job-processing-system-celery-worker"
frontend_repo="distributed-job-processing-system-frontend"

delete_repo() {
  local repo_name="$1"

  if ! aws ecr describe-repositories --repository-names "$repo_name" --region "$aws_region" >/dev/null 2>&1; then
    echo "repository not found, skipping: $repo_name"
    return
  fi

  echo "deleting repository: $repo_name"
  aws ecr delete-repository \
    --repository-name "$repo_name" \
    --region "$aws_region" \
    --force >/dev/null
}

echo "tearing down ECR repositories in ${aws_account_id}.dkr.ecr.${aws_region}.amazonaws.com"
delete_repo "$api_repo"
delete_repo "$worker_repo"
delete_repo "$frontend_repo"

echo "done"
