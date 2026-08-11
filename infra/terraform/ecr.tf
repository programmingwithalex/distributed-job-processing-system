resource "aws_ecr_repository" "application" {
  for_each = var.ecr_repository_names

  name         = each.value
  force_delete = true
  # prevent a commit SHA tag from being overwritten with different image contents
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
