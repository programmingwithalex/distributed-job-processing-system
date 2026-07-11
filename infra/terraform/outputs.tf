output "aws_region" {
  description = "AWS region used for this stack"
  value       = var.aws_region
}

output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "kubeconfig_command" {
  description = "Command to update local kubeconfig for this cluster"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "ecr_repository_urls" {
  description = "ECR repository URLs used by the application images"
  value = {
    for key, repository in aws_ecr_repository.application : key => repository.repository_url
  }
}

output "aws_account_id" {
  description = "AWS account ID resolved from the current credentials"
  value       = data.aws_caller_identity.current.account_id
}

output "publish_images_example" {
  description = "Example command to publish images after Terraform apply"
  value       = "bash infra/k8s/overlays/eks/publish-images.sh"
}
