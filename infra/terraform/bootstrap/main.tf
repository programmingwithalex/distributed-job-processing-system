provider "aws" {
  # bootstrap resources are intentionally retained independently of the EKS stack
  region = var.aws_region
}

# append entropy to the state bucket name because S3 bucket names are global
resource "random_id" "state_bucket_suffix" {
  byte_length = 4
}

# persist the main EKS Terraform state outside the EKS lifecycle
resource "aws_s3_bucket" "terraform_state" {
  bucket        = "dist-jobs-tf-state-${data.aws_caller_identity.current.account_id}-${random_id.state_bucket_suffix.hex}"
  force_destroy = false

  tags = {
    ManagedBy = "terraform"
    Purpose   = "terraform-state"
    Project   = var.project_name
  }
}

# reject any public access path to the state bucket
resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# disable ACLs so the owning AWS account controls every state object
resource "aws_s3_bucket_ownership_controls" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# retain prior state revisions for recovery from accidental or failed changes
resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# use AWS-managed server-side encryption for all stored Terraform state objects
resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# -----------------------------------------------------------------------------
# github actions oidc authentication
# replaces stored aws iam user credentials with short-lived sts role credentials
# visible in aws iam at roles → dist-jobs-github-actions → trust relationships
# -----------------------------------------------------------------------------

# retrieve GitHub's current certificate thumbprint for the AWS OIDC provider
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

# establish GitHub Actions as a federated identity provider in this AWS account
# this replaces stored AWS IAM user access keys with short-lived role credentials
resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

# construct the trust policy that governs who may assume the deployment role
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      # use the provider ARN rather than a hardcoded account-specific value
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      # accept only GitHub-issued tokens intended for AWS STS
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      # restrict role assumption to workflow runs from the configured repository branch
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/${var.github_actions_branch}"]
    }
  }
}

# issue short-lived AWS credentials to approved GitHub Actions workflow runs
# workflows authenticate with GitHub OIDC rather than AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
resource "aws_iam_role" "github_actions" {
  name               = "dist-jobs-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json

  tags = {
    ManagedBy = "terraform"
    Project   = var.project_name
    Purpose   = "github-actions"
  }
}

# define the permissions required to provision, deploy, verify, and destroy this environment
data "aws_iam_policy_document" "github_actions_environment_management" {
  statement {
    # discover the state bucket configuration and enumerate the configured state prefix
    sid       = "TerraformState"
    effect    = "Allow"
    actions   = ["s3:GetBucketVersioning", "s3:ListBucket"]
    resources = [aws_s3_bucket.terraform_state.arn]
  }

  statement {
    # read, update, and remove the state object and S3 native lockfile
    sid    = "TerraformStateObjects"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.terraform_state.arn}/distributed-job-processing-system/dev/*"]
  }

  statement {
    # publish application images and remove the repositories during Terraform teardown
    sid    = "EcrRepositories"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchDeleteImage",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:CreateRepository",
      "ecr:DeleteRepository",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:ListTagsForResource",
      "ecr:PutImage",
      "ecr:PutImageScanningConfiguration",
      "ecr:TagResource",
      "ecr:UntagResource",
      "ecr:UploadLayerPart",
    ]
    resources = ["arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/distributed-job-processing-system-*"]
  }

  statement {
    # ECR authorization tokens do not support repository-level resource restrictions
    sid       = "EcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    # Terraform EKS and VPC modules require these AWS control-plane lifecycle actions
    sid    = "EksAndSupportingInfrastructure"
    effect = "Allow"
    actions = [
      "ec2:AllocateAddress",
      "ec2:AssociateRouteTable",
      "ec2:AttachInternetGateway",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateInternetGateway",
      "ec2:CreateLaunchTemplate",
      "ec2:CreateNetworkAclEntry",
      "ec2:CreateNatGateway",
      "ec2:CreateRoute",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
      "ec2:CreateTags",
      "ec2:CreateVpc",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteLaunchTemplate",
      "ec2:DeleteNetworkAclEntry",
      "ec2:DeleteNatGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteTags",
      "ec2:DeleteVpc",
      "ec2:Describe*",
      "ec2:DetachInternetGateway",
      "ec2:DisassociateRouteTable",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:ReleaseAddress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "eks:AssociateAccessPolicy",
      "eks:CreateAccessEntry",
      "eks:CreateAddon",
      "eks:CreateCluster",
      "eks:CreateNodegroup",
      "eks:DeleteAccessEntry",
      "eks:DeleteAddon",
      "eks:DeleteCluster",
      "eks:DeleteNodegroup",
      "eks:DescribeAddon",
      "eks:DescribeCluster",
      "eks:DescribeNodegroup",
      "eks:DescribeUpdate",
      "eks:DisassociateAccessPolicy",
      "eks:ListAddons",
      "eks:ListNodegroups",
      "eks:ListTagsForResource",
      "eks:TagResource",
      "eks:UntagResource",
      "eks:UpdateAddon",
      "iam:AttachRolePolicy",
      "iam:CreateOpenIDConnectProvider",
      "iam:CreatePolicy",
      "iam:CreateRole",
      "iam:DeleteOpenIDConnectProvider",
      "iam:DeletePolicy",
      "iam:DeleteRole",
      "iam:DetachRolePolicy",
      "iam:GetOpenIDConnectProvider",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:GetRole",
      "iam:ListAttachedRolePolicies",
      "iam:ListPolicyVersions",
      "iam:ListRolePolicies",
      "iam:PassRole",
      "iam:TagOpenIDConnectProvider",
      "iam:TagPolicy",
      "iam:TagRole",
      "iam:UntagOpenIDConnectProvider",
      "iam:UntagPolicy",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "kms:CreateAlias",
      "kms:CreateKey",
      "kms:DescribeKey",
      "kms:DisableKey",
      "kms:EnableKeyRotation",
      "kms:GetKeyPolicy",
      "kms:GetKeyRotationStatus",
      "kms:ListAliases",
      "kms:ListResourceTags",
      "kms:PutKeyPolicy",
      "kms:ScheduleKeyDeletion",
      "kms:TagResource",
      "kms:UntagResource",
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DescribeLogGroups",
      "logs:ListTagsForResource",
      "logs:TagResource",
      "logs:UntagResource",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeTargetGroups",
      "tag:GetResources",
    ]
    resources = ["*"]
  }
}

# attach the environment-management policy directly to the federated deployment role
resource "aws_iam_role_policy" "github_actions_environment_management" {
  name   = "dist-jobs-environment-management"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_environment_management.json
}

# resolve the account ID for globally unique names and account-scoped policy resources
data "aws_caller_identity" "current" {}