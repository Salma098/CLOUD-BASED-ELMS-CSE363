# Project Configuration
project_name = "cse363"
environment  = "dev"
aws_region   = "us-east-1"
aws_account_id = "181617012032"

# Networking
vpc_cidr             = "10.0.0.0/16"
availability_zones   = ["us-east-1a", "us-east-1b"]
public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
private_subnet_cidrs = ["10.0.10.0/24", "10.0.11.0/24"]
data_subnet_cidrs    = ["10.0.20.0/24", "10.0.21.0/24"]

# Services
service_names = ["chat", "document", "tts", "stt", "quiz"]

service_security_groups = {
  chat     = "sg-035dd542c6c2f8228"
  document = "sg-02e7f5c8b273a152b"
  tts      = "sg-0d17312782faf20eb"
  stt      = "sg-03c036739dc4136b6"
  quiz     = "sg-0619be87781d80eca"
}

service_role_arns = {
  chat     = "arn:aws:iam::701679164136:role/LabRole"
  document = "arn:aws:iam::701679164136:role/LabRole"
  tts      = "arn:aws:iam::701679164136:role/LabRole"
  stt      = "arn:aws:iam::701679164136:role/LabRole"
  quiz     = "arn:aws:iam::701679164136:role/LabRole"
}


# Database
database_services    = ["chat", "document", "quiz"]
db_instance_class    = "db.t3.micro"
db_allocated_storage = 20
db_master_username   = "dbadmin"
db_master_password   = "CHANGE_ME_IN_PRODUCTION"  # Use AWS Secrets Manager in production

