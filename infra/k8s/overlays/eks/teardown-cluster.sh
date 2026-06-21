#!/usr/bin/env bash

# **************************************************** #
# ** usage ** #

# CLUSTER_NAME=dist-jobs
# AWS_REGION=us-east-1
# bash infra/k8s/overlays/eks/teardown-cluster.sh "$CLUSTER_NAME" "$AWS_REGION"

# **************************************************** #

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <cluster-name> <aws-region>"
  echo "example: $0 dist-jobs us-east-1"
  exit 1
fi

cluster_name="$1"
aws_region="$2"

echo "warning: deleting the EKS cluster will also remove its worker nodes and load balancers"
echo "deleting cluster: ${cluster_name} in region: ${aws_region}"

eksctl delete cluster --name "$cluster_name" --region "$aws_region"

echo "done"
