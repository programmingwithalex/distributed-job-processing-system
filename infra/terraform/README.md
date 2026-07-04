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
- `verify-resources.sh` checks the Terraform-created AWS resources from Bash with Terraform outputs and the AWS CLI
- `verify-resources.ps1` checks the Terraform-created AWS resources with Terraform outputs and the AWS CLI
- `terraform.tfvars.example` shows safe example input values

## Usage

Initialize Terraform:

```bash
terraform -chdir=infra/terraform init
```

`terraform init` creates `.terraform.lock.hcl`, which records the exact provider versions selected for this configuration. Keep that lock file in version control so everyone uses the same provider versions unless you intentionally upgrade them.

When you intentionally want newer provider or module releases that still satisfy the version constraints in this configuration, run:

```bash
terraform -chdir=infra/terraform init -upgrade
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
AWS_ACCOUNT_ID=$(terraform -chdir=infra/terraform output -raw aws_account_id)
AWS_REGION=$(terraform -chdir=infra/terraform output -raw aws_region)

bash infra/k8s/overlays/eks/publish-images.sh "$AWS_ACCOUNT_ID" "$AWS_REGION" <image_tag>
kubectl apply -k infra/k8s/overlays/eks
```

## Destroy Instructions

AWS charges continue until the EKS cluster, node group, NAT gateway, and load balancer resources are destroyed.

Before `terraform destroy`, remove Kubernetes resources first so Kubernetes can clean up the ingress load balancer:

```bash
kubectl delete -k infra/k8s/overlays/eks --ignore-not-found
kubectl delete -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml --ignore-not-found
```

Wait until the ingress load balancer is gone, then destroy the AWS infrastructure:

```bash
terraform -chdir=infra/terraform destroy -var-file=terraform.tfvars
```
