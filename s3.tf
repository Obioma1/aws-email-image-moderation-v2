# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

# Store incoming emails and extracted image attachments.
# incoming/ - Raw emails received through Amazon SES.
# images/   - Image attachments extracted by AWS Lambda.
resource "aws_s3_bucket" "mail" {
  bucket_prefix = "${var.project_name}-"

  # Prevent accidental deletion of a non-empty bucket.
  force_destroy = false

  tags = {
    Project   = var.project_name
    Component = "EmailImageStorage"
    ManagedBy = "Terraform"
  }
}

# Block all public access to the S3 bucket.
# Flagged images are accessed using temporary presigned URLs.
resource "aws_s3_bucket_public_access_block" "mail" {
  bucket = aws_s3_bucket.mail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable default server-side encryption for stored objects.
resource "aws_s3_bucket_server_side_encryption_configuration" "mail" {
  bucket = aws_s3_bucket.mail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Automatically expire stored emails and extracted images
# after 30 days to reduce unnecessary storage costs.
resource "aws_s3_bucket_lifecycle_configuration" "mail" {
  bucket = aws_s3_bucket.mail.id

  rule {
    id     = "expire-email-moderation-objects"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}

# Permit Amazon SES to store incoming emails in S3.
# Access is restricted to this AWS account and the incoming/ prefix.
resource "aws_s3_bucket_policy" "ses" {
  bucket = aws_s3_bucket.mail.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowSESIncomingEmailStorage"
        Effect = "Allow"

        Principal = {
          Service = "ses.amazonaws.com"
        }

        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.mail.arn}/incoming/*"

        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# Trigger Lambda whenever Amazon SES stores a new email.
# Only incoming/ objects trigger processing.
# Images written to images/ will not trigger Lambda again.
resource "aws_s3_bucket_notification" "incoming" {
  bucket = aws_s3_bucket.mail.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.moderate.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "incoming/"
  }

  # Ensure Lambda permits S3 invocation before notification setup.
  depends_on = [aws_lambda_permission.s3]
}
