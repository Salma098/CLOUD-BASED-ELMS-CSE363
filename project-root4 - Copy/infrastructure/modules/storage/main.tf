resource "aws_s3_bucket" "service_buckets" {
  for_each = toset(var.service_names)

  bucket = "${var.project_name}-${each.key}-storage-${var.environment}"

  tags = {
    Name        = "${var.project_name}-${each.key}-storage"
    Environment = var.environment
    Service     = each.key
  }
}
