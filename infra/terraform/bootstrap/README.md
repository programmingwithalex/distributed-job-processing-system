# Terraform State Bootstrap

This configuration creates the persistent S3 bucket used by the EKS stack. It intentionally uses local Terraform state because the remote bucket does not exist yet.

Run once from the repository root:

```bash
terraform -chdir=infra/terraform/bootstrap init
terraform -chdir=infra/terraform/bootstrap apply
```

Copy the displayed `state_bucket_name` into `infra/terraform/backend.hcl` using [../backend.hcl.example](../backend.hcl.example), then migrate the existing EKS state when prompted:

```bash
terraform -chdir=infra/terraform init -migrate-state -backend-config=backend.hcl
```

The EKS destroy workflow must never destroy this bootstrap configuration. Bucket versioning and S3 native lockfiles protect the shared state; `force_destroy` remains disabled so bucket deletion requires deliberate manual cleanup.