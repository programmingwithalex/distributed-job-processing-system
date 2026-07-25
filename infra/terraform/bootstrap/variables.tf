variable "aws_region" {
  description = "AWS region that stores the Terraform state bucket"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project identifier used in the state bucket name"
  type        = string
  default     = "distributed-job-processing-system"
}

variable "github_repository" {
  description = "GitHub owner and repository allowed to assume the deployment role"
  type        = string
  default     = "programmingwithalex/distributed-job-processing-system"
}

variable "github_actions_branch" {
  description = "Git branch allowed to assume the deployment role"
  type        = string
  default     = "main"
}