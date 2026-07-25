resource "aws_ecr_repository" "application" {
  for_each = var.ecr_repository_names

  name                 = each.value
  force_delete         = true
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
