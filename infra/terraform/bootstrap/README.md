# Terraform State Bootstrap

This configuration creates the persistent S3 bucket used by the EKS stack. It intentionally uses local Terraform state because the remote bucket does not exist yet.

The generated bucket suffix ensures global S3 name uniqueness only. After bootstrap apply, the resulting `state_bucket_name` is stable and should be saved as the `TF_STATE_BUCKET` GitHub repository variable. Normal EKS teardown and recreation reuse the same bucket, so this variable does not need to be changed between environment lifecycles.

For the complete operator checklist, including GitHub Actions configuration and state migration, use [../README.md](../README.md#team-environment-setup-and-operations).

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
