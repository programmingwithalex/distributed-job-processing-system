#!/usr/bin/env bash

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-dist-jobs}"
NAMESPACE="${NAMESPACE:-dist-jobs}"
TERRAFORM_VAR_FILE="${TERRAFORM_VAR_FILE:-terraform.tfvars}"
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"

require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

wait_for_namespace_deletion() {
  local namespace="$1"

  if kubectl get namespace "$namespace" >/dev/null 2>&1; then
    kubectl wait --for=delete "namespace/${namespace}" --timeout=10m
  fi
}

if [[ "${1:-}" != "--confirm" ]]; then
  echo "usage: $0 --confirm" >&2
  echo "this deletes the Kubernetes application stack and all Terraform-managed AWS resources" >&2
  exit 1
fi

require_command aws
require_command terraform

if aws eks describe-cluster --region "$AWS_REGION" --name "$CLUSTER_NAME" >/dev/null 2>&1; then
  require_command kubectl

  echo "updating kubeconfig for ${CLUSTER_NAME}"
  aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

  echo "deleting application namespace ${NAMESPACE}"
  kubectl delete -k "$repo_root/infra/k8s/overlays/eks" --ignore-not-found
  wait_for_namespace_deletion "$NAMESPACE"

  echo "deleting ingress-nginx"
  kubectl delete -f "$INGRESS_NGINX_MANIFEST" --ignore-not-found
  wait_for_namespace_deletion ingress-nginx
else
  echo "EKS cluster ${CLUSTER_NAME} is already absent; reconciling Terraform state"
fi

echo "destroying Terraform-managed AWS resources"
terraform_destroy_arguments=(-auto-approve)

if [[ -f "$repo_root/infra/terraform/$TERRAFORM_VAR_FILE" ]]; then
  terraform_destroy_arguments=("-var-file=${TERRAFORM_VAR_FILE}" "${terraform_destroy_arguments[@]}")
fi

terraform -chdir="$repo_root/infra/terraform" destroy "${terraform_destroy_arguments[@]}"

echo "verifying Terraform state is empty"
if terraform -chdir="$repo_root/infra/terraform" state list | grep -q .; then
  echo "Terraform state still contains managed resources" >&2
  exit 1
fi

echo "EKS application stack destroyed"