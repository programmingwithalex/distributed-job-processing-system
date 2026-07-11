resource "aws_ecr_repository" "application" {
  for_each = var.ecr_repository_names

  name                 = each.value
  # immutable tags are the better long-term default, but mutable tags support the current deployment workflow
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
