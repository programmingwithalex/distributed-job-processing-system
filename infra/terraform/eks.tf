module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.14"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  cluster_endpoint_public_access = var.cluster_endpoint_public_access

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # declare stable cluster administrators instead of deriving access from the Terraform caller
  enable_cluster_creator_admin_permissions = false

  access_entries = {
    administrator = {
      principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/admin"

      policy_associations = {
        cluster_admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }

    github_actions = {
      principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/dist-jobs-github-actions"

      policy_associations = {
        cluster_admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  # install the baseline EKS-managed addons instead of configuring them manually after cluster creation
  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = {}
  }

  eks_managed_node_groups = {
    default = {
      # use a single default node group to keep the initial cluster footprint predictable
      instance_types = var.node_instance_types
      desired_size   = var.node_desired_size
      min_size       = var.node_min_size
      max_size       = var.node_max_size
    }
  }
}
