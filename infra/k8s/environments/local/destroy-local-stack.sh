#!/usr/bin/env bash

set -euo pipefail

# allow callers to target another local cluster while keeping the deployment default
CLUSTER_NAME="${CLUSTER_NAME:-distributed-jobs}"

# fail before attempting cleanup when the local k3d command is unavailable
require_command() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

require_command k3d

# keep cleanup repeatable when the requested cluster has already been removed
cluster_exists=false
while read -r cluster_name _; do
  if [[ "$cluster_name" == "$CLUSTER_NAME" ]]; then
    cluster_exists=true
    break
  fi
done < <(k3d cluster list --no-headers)

if [[ "$cluster_exists" == false ]]; then
  echo "local cluster ${CLUSTER_NAME} is already absent"
  exit 0
fi

# deleting the cluster removes its workloads, ingress, monitoring stack, and storage
echo "deleting k3d cluster ${CLUSTER_NAME}"
if k3d cluster delete "$CLUSTER_NAME"; then
  echo "local cluster ${CLUSTER_NAME} deleted"
else
  echo "local cluster ${CLUSTER_NAME} could not be deleted" >&2
  exit 1
fi

cat <<EOF

The local Kubernetes stack has been removed.
Locally built Docker images were kept for faster future deployments.
EOF