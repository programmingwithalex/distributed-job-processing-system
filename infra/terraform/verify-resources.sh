#!/usr/bin/env bash

set -euo pipefail

TERRAFORM_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

require_command() {
  local name="$1"

  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Required command '$name' was not found in PATH." >&2
    exit 1
  fi
}

terraform_output_raw() {
  local name="$1"
  terraform -chdir="$TERRAFORM_DIR" output -raw "$name"
}

print_success() {
  printf '[ok] %s\n' "$1"
}

print_failure() {
  printf '[fail] %s\n' "$1"
}

require_command terraform
require_command aws
require_command python3

failures=()

region="$(terraform_output_raw aws_region)"
cluster_name="$(terraform_output_raw cluster_name)"
expected_account_id="$(terraform_output_raw aws_account_id)"

caller_account="$(aws sts get-caller-identity --query 'Account' --output text)"

if [[ "$caller_account" == "$expected_account_id" ]]; then
  print_success "AWS CLI is authenticated to account $caller_account."
else
  failures+=("AWS CLI account '$caller_account' does not match Terraform output '$expected_account_id'.")
  print_failure "AWS CLI account '$caller_account' does not match Terraform output '$expected_account_id'."
fi

cluster_status="$(aws eks describe-cluster --name "$cluster_name" --region "$region" --query 'cluster.status' --output text)"

if [[ "$cluster_status" == "ACTIVE" ]]; then
  print_success "EKS cluster '$cluster_name' is ACTIVE."
else
  failures+=("EKS cluster '$cluster_name' status is '$cluster_status', expected 'ACTIVE'.")
  print_failure "EKS cluster '$cluster_name' status is '$cluster_status', expected 'ACTIVE'."
fi

vpc_id="$(aws eks describe-cluster --name "$cluster_name" --region "$region" --query 'cluster.resourcesVpcConfig.vpcId' --output text)"
subnet_ids_text="$(aws eks describe-cluster --name "$cluster_name" --region "$region" --query 'cluster.resourcesVpcConfig.subnetIds' --output text)"
read -r -a subnet_ids <<< "$subnet_ids_text"

vpc_count="$(aws ec2 describe-vpcs --vpc-ids "$vpc_id" --region "$region" --query 'length(Vpcs)' --output text)"

if [[ "$vpc_count" == "1" ]]; then
  print_success "VPC '$vpc_id' exists."
else
  failures+=("Expected VPC '$vpc_id' to exist.")
  print_failure "Expected VPC '$vpc_id' to exist."
fi

subnet_count="$(aws ec2 describe-subnets --region "$region" --subnet-ids "${subnet_ids[@]}" --query 'length(Subnets)' --output text)"

if [[ "$subnet_count" == "${#subnet_ids[@]}" ]]; then
  print_success "All cluster subnets exist in AWS."
else
  failures+=("Expected ${#subnet_ids[@]} cluster subnets, found $subnet_count.")
  print_failure "Expected ${#subnet_ids[@]} cluster subnets, found $subnet_count."
fi

nat_count="$(aws ec2 describe-nat-gateways --region "$region" --filter "Name=vpc-id,Values=$vpc_id" "Name=state,Values=available" --query 'length(NatGateways)' --output text)"

if [[ "$nat_count" =~ ^[0-9]+$ ]] && (( nat_count >= 1 )); then
  print_success "At least one NAT gateway is available in VPC '$vpc_id'."
else
  failures+=("No available NAT gateways were found in VPC '$vpc_id'.")
  print_failure "No available NAT gateways were found in VPC '$vpc_id'."
fi

mapfile -t nodegroup_names < <(aws eks list-nodegroups --cluster-name "$cluster_name" --region "$region" --query 'nodegroups' --output text | tr '\t' '\n' | sed '/^$/d')

if (( ${#nodegroup_names[@]} == 0 )); then
  failures+=("No managed node groups were found for cluster '$cluster_name'.")
  print_failure "No managed node groups were found for cluster '$cluster_name'."
fi

for nodegroup_name in "${nodegroup_names[@]}"; do
  nodegroup_status="$(aws eks describe-nodegroup --cluster-name "$cluster_name" --nodegroup-name "$nodegroup_name" --region "$region" --query 'nodegroup.status' --output text)"

  if [[ "$nodegroup_status" == "ACTIVE" ]]; then
    print_success "Node group '$nodegroup_name' is ACTIVE."
  else
    failures+=("Node group '$nodegroup_name' status is '$nodegroup_status', expected 'ACTIVE'.")
    print_failure "Node group '$nodegroup_name' status is '$nodegroup_status', expected 'ACTIVE'."
  fi
done

mapfile -t repository_records < <(
  terraform -chdir="$TERRAFORM_DIR" output -json ecr_repository_urls |
    python3 -c 'import json, sys
data = json.load(sys.stdin)
for _, url in sorted(data.items()):
    print(f"{url.rsplit('/', 1)[-1]}|{url}")'
)

if (( ${#repository_records[@]} == 0 )); then
  echo "No aws_ecr_repository.application instances were found in Terraform state." >&2
  exit 1
fi

declare -A repository_uris_by_name=()

for repository_record in "${repository_records[@]}"; do
  repository_name="${repository_record%%|*}"
  repository_uris_by_name["$repository_name"]="${repository_record#*|}"
done

for repository_name in "${!repository_uris_by_name[@]}"; do
  expected_repository_uri="${repository_uris_by_name[$repository_name]}"
  actual_repository_uri="$(aws ecr describe-repositories --repository-names "$repository_name" --region "$region" --query 'repositories[0].repositoryUri' --output text)"

  if [[ "$actual_repository_uri" == "$expected_repository_uri" ]]; then
    print_success "ECR repository '$repository_name' exists."
  else
    failures+=("ECR repository '$repository_name' did not match the Terraform output URI.")
    print_failure "ECR repository '$repository_name' did not match the Terraform output URI."
  fi
done

if (( ${#failures[@]} > 0 )); then
  printf '\nVerification failed:\n' >&2

  for failure in "${failures[@]}"; do
    printf ' - %s\n' "$failure" >&2
  done

  exit 1
fi

printf '\nTerraform-managed AWS resources verified successfully.\n'