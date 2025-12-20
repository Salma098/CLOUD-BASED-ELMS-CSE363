# DB Subnet Group
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-${var.environment}-db-subnet-group"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-subnet-group"
    Environment = var.environment
  }
}

# RDS Instances for each service
resource "aws_db_instance" "service_databases" {
  for_each = toset(var.database_services)

  identifier        = "${var.project_name}-${var.environment}-${each.key}-db"
  engine            = "postgres"
  engine_version    = "15.4"
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage

  db_name  = replace("${each.key}_${var.environment}", "-", "_")
  username = var.db_master_username
  password = var.db_master_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds[each.key].id]

  multi_az               = var.environment == "production" ? true : false
  publicly_accessible    = false
  storage_encrypted      = true
  kms_key_id            = aws_kms_key.rds_keys[each.key].arn
  backup_retention_period = 7
  backup_window          = "03:00-04:00"
  maintenance_window     = "Mon:04:00-Mon:05:00"

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  skip_final_snapshot       = var.environment != "production"
  final_snapshot_identifier = "${var.project_name}-${var.environment}-${each.key}-final-snapshot"

  tags = {
    Name        = "${var.project_name}-${var.environment}-${each.key}-db"
    Environment = var.environment
    Service     = each.key
  }
}

# KMS Keys for RDS encryption
resource "aws_kms_key" "rds_keys" {
  for_each = toset(var.database_services)

  description             = "KMS key for ${each.key} RDS encryption"
  deletion_window_in_days = 10
  enable_key_rotation     = true

  tags = {
    Name        = "${var.project_name}-${var.environment}-${each.key}-rds-key"
    Environment = var.environment
    Service     = each.key
  }
}

# Security Groups for RDS
resource "aws_security_group" "rds" {
  for_each = toset(var.database_services)

  name        = "${var.project_name}-${var.environment}-${each.key}-rds-sg"
  description = "Security group for ${each.key} RDS instance"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from ${each.key} service"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = ["10.0.0.0/16"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-${each.key}-rds-sg"
    Environment = var.environment
    Service     = each.key
  }
}

