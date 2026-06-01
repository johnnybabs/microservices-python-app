locals {
  common_tags = {
    Project     = "vidcast"
    ManagedBy   = "terraform"
    Environment = "dev"
    Region      = var.aws_region
  }
}

module "vpc" {
  source = "../../modules/vpc"

  cluster_name       = var.cluster_name
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  tags               = local.common_tags
}

module "iam" {
  source = "../../modules/iam"

  cluster_name = var.cluster_name
  tags         = local.common_tags
}

module "eks" {
  source = "../../modules/eks"

  cluster_name       = var.cluster_name
  kubernetes_version = var.kubernetes_version
  cluster_role_arn   = module.iam.cluster_role_arn
  node_role_arn      = module.iam.node_role_arn
  subnet_ids         = module.vpc.public_subnet_ids
  node_instance_type = var.node_instance_type
  node_min_count     = var.node_min_count
  node_max_count     = var.node_max_count
  node_desired_count = var.node_desired_count
  tags               = local.common_tags
}

module "security_groups" {
  source = "../../modules/security-groups"

  cluster_name   = var.cluster_name
  vpc_id         = module.vpc.vpc_id
  nodeport_ports = [30002, 30003, 30004, 30005, 30006, 30007, 30008]
  tags           = local.common_tags
}
