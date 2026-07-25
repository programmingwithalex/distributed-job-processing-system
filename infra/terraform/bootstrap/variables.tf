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