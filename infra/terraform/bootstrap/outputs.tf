output "state_bucket_name" {
  description = "S3 bucket name for the EKS Terraform state"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "aws_region" {
  description = "AWS region containing the Terraform state bucket"
  value       = var.aws_region
}

output "github_actions_role_arn" {
  description = "IAM role ARN assumed by GitHub Actions through OIDC"
  value       = aws_iam_role.github_actions.arn
}