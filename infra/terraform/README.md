# Terraform AWS Foundation

This directory recreates the AWS infrastructure that was previously proven manually with `eksctl`, ECR, and the EKS Kustomize overlay.

Terraform manages the AWS foundation only:

- VPC and networking
- EKS cluster and managed node group
- ECR repositories for the API, Celery worker, and frontend images

Terraform does not manage Kubernetes application resources. Continue to deploy the application with [../k8s/overlays/eks/kustomization.yaml](../k8s/overlays/eks/kustomization.yaml).

## Files

- `versions.tf` pins Terraform and provider versions
- `providers.tf` configures the AWS provider and default tags
- `variables.tf` declares reusable inputs
- `locals.tf` derives shared names, tags, and AWS data sources
- `network.tf` creates the VPC, public/private subnets, NAT, and route wiring through the VPC module
- `iam.tf` documents that the EKS module manages the required IAM roles and policy attachments
- `eks.tf` creates the EKS cluster and managed node group through the EKS module
- `ecr.tf` creates the three ECR repositories used by the application images
- `outputs.tf` exposes kubeconfig and image-publishing values
- `backend.hcl.example` shows the uncommitted S3 backend settings for the EKS state
- `bootstrap/` creates the persistent S3 state bucket that survives EKS teardown
- `verify-resources.sh` checks the Terraform-created AWS resources from Bash with Terraform outputs and the AWS CLI
- `verify-resources.ps1` checks the Terraform-created AWS resources with Terraform outputs and the AWS CLI
- `terraform.tfvars.example` shows safe example input values

## Usage

## One-time Remote State Setup

The EKS environment lifecycle is managed separately from its persistent Terraform state bucket. Create the bucket once with the bootstrap configuration:

```bash
terraform -chdir=infra/terraform/bootstrap init
terraform -chdir=infra/terraform/bootstrap apply
```

Copy [backend.hcl.example](./backend.hcl.example) to an uncommitted `backend.hcl`, replacing the bucket name with the bootstrap `state_bucket_name` output. Then initialize the EKS stack with S3 versioning, encryption, and native S3 lockfiles:

```bash
terraform -chdir=infra/terraform init -migrate-state -backend-config=backend.hcl
```

If the EKS stack has never been applied, omit `-migrate-state`. Do not destroy `infra/terraform/bootstrap` during EKS teardown; it protects the state needed to recreate the environment.

## Local Usage

Initialize Terraform:

```bash
terraform -chdir=infra/terraform init -backend-config=backend.hcl
```

`terraform init` creates `.terraform.lock.hcl`, which records the exact provider versions selected for this configuration. Keep that lock file in version control so everyone uses the same provider versions unless you intentionally upgrade them.

When you intentionally want newer provider or module releases that still satisfy the version constraints in this configuration, run:

```bash
terraform -chdir=infra/terraform init -upgrade -backend-config=backend.hcl
```

This refreshes the dependency selections and updates `.terraform.lock.hcl` to the newer allowed versions.

Create a local tfvars file from the example:

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Review the plan:

```bash
terraform -chdir=infra/terraform plan -var-file=terraform.tfvars
```

Apply (build) the infrastructure on AWS:

```bash
terraform -chdir=infra/terraform apply -var-file=terraform.tfvars
```

Verify the Terraform-created AWS resources before moving on to image publishing and Kubernetes deployment:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\terraform\verify-resources.ps1
```

```bash
bash infra/terraform/verify-resources.sh
```

The verification scripts confirm the active AWS account, EKS cluster, managed node groups, VPC/subnets/NAT gateway, and ECR repositories recorded in Terraform state. The Bash version uses `python3` for Terraform JSON parsing.

After apply, update kubeconfig using the output command:

```bash
terraform -chdir=infra/terraform output -raw kubeconfig_command
```

Then publish images and deploy the application overlay:

```bash
bash infra/k8s/overlays/eks/deploy-eks-application-stack.sh
```

`publish-images.sh` assigns a Git commit SHA tag by default. Override `IMAGE_TAG` only with another immutable identifier.

## Destroy Instructions

AWS charges continue until the EKS cluster, node group, NAT gateway, and load balancer resources are destroyed.

Before `terraform destroy`, remove Kubernetes resources first so Kubernetes can clean up the ingress load balancer:

```bash
kubectl delete -k infra/k8s/overlays/eks --ignore-not-found
kubectl delete -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml --ignore-not-found
```

Wait until the ingress load balancer is gone, then destroy the AWS infrastructure:

```bash
bash infra/k8s/overlays/eks/destroy-eks-application-stack.sh --confirm
```

The helper deletes Kubernetes and ingress resources, waits for namespace cleanup, and runs Terraform destroy. ECR repositories use `force_delete = true`, so pushed images do not block teardown.

## GitHub Actions Development Lifecycle

The workflows are manual and use one shared concurrency group, so deploy and destroy cannot run at the same time:

- **Continuous Integration** runs backend lint/tests and frontend build/end-to-end checks for every pull request.
- **Deploy EKS Environment** provisions the Terraform stack, publishes commit-SHA-tagged images, deploys the application, and reports the ingress endpoint.
- **Destroy EKS Environment** requires the exact confirmation value `DESTROY`, then removes the application and all Terraform-managed EKS resources.

Before using the deploy or destroy workflows, configure these repository values and secrets:

| Type | Name | Value |
| --- | --- | --- |
| Variable | `AWS_REGION` | AWS region, such as `us-east-1` |
| Variable | `TF_STATE_BUCKET` | `state_bucket_name` from the bootstrap output |
| Secret | `AWS_ACCESS_KEY_ID` | Access key for the dedicated environment-management IAM principal |
| Secret | `AWS_SECRET_ACCESS_KEY` | Matching secret access key |

The IAM principal must be limited to the intended AWS account and permitted to manage the Terraform-created EKS, EC2/VPC, ECR, IAM, CloudWatch, and S3-state resources. Rotate these long-lived keys regularly. The workflow never prints secret values.
