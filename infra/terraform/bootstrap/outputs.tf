output "state_bucket_name" {
  description = "S3 bucket name for the EKS Terraform state"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "aws_region" {
  description = "AWS region containing the Terraform state bucket"
  value       = var.aws_region
}