variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "service_names" {
  type = list(string)
}

variable "aws_account_id" {
  type = string
}

variable "service_role_arns" {
  type = map(string)
}
