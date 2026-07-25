variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project identifier used in naming"
  type        = string
  default     = "distributed-job-processing-system"
}

variable "environment" {
  description = "Environment name used in resource tags and names"
  type        = string
  default     = "eks"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "dist-jobs"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.36"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones to use for subnets"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.0.0/20", "10.0.16.0/20"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.128.0/20", "10.0.144.0/20"]
}

variable "cluster_endpoint_public_access" {
  description = "Whether the EKS API endpoint should be publicly reachable"
  type        = bool
  default     = true
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed node group"
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_desired_size" {
  description = "Desired node count for the managed node group"
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum node count for the managed node group"
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum node count for the managed node group"
  type        = number
  default     = 3
}

variable "ecr_repository_names" {
  description = "ECR repository names for application images"
  type        = map(string)

  default = {
    api           = "distributed-job-processing-system-api"
    celery_worker = "distributed-job-processing-system-celery-worker"
    frontend      = "distributed-job-processing-system-frontend"
  }
}

variable "tags" {
  description = "Additional tags applied to all Terraform-managed resources"
  type        = map(string)
  default     = {}
}
