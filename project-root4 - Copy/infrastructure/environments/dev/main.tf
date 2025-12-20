terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Networking Module
module "networking" {
  source = "../../modules/networking"

  project_name         = var.project_name
  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  data_subnet_cidrs    = var.data_subnet_cidrs
}

# Storage Module
module "storage" {
  source = "../../modules/storage"

  project_name      = var.project_name
  environment       = var.environment
  service_names     = var.service_names
  aws_account_id    = var.aws_account_id
  service_role_arns = var.service_role_arns
}

# Database Module
module "database" {
  source = "../../modules/database"

  project_name             = var.project_name
  environment              = var.environment
  vpc_id                   = module.networking.vpc_id
  subnet_ids               = module.networking.data_subnet_ids
  database_services        = var.database_services
  db_instance_class        = var.db_instance_class
  db_allocated_storage     = var.db_allocated_storage
  db_master_username       = var.db_master_username
  db_master_password       = var.db_master_password
  service_security_groups  = var.service_security_groups
}

