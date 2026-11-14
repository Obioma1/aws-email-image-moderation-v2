# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================


# The Lambda deployment package is built separately using:
#
# bash scripts/build-lambda.sh
#
# The ZIP includes handler.py and Linux-compatible Pillow.
# Build the ZIP before running terraform plan or apply.

locals {
  lambda_package = "${path.module}/lambda.zip"
}

# Deploy the serverless email image moderation function.
resource "aws_lambda_function" "moderate" {
  function_name = var.project_name
  role          = aws_iam_role.lambda.arn

  runtime       = "python3.13"
  architectures = ["x86_64"]
  handler       = "handler.handler"

  # Use the complete Docker-built deployment package.
  filename         = local.lambda_package
  source_code_hash = filebase64sha256(local.lambda_package)

  memory_size = 512
  timeout     = 180

  # Pass application configuration to the Python handler.
  environment {
    variables = {
      BUCKET               = aws_s3_bucket.mail.id
      SENDER_EMAIL         = local.sender_email
      APPROVED_EMAIL       = var.approved_email
      FLAGGED_EMAIL        = var.flagged_email
      MODERATION_THRESHOLD = tostring(var.moderation_threshold)
      LINK_EXPIRY_SECONDS  = tostring(var.link_expiry_seconds)
    }
  }

  tags = {
    Project   = var.project_name
    Component = "EmailModerationLambda"
    ManagedBy = "Terraform"
  }

  # Ensure logging resources and IAM permissions exist first.
  depends_on = [
    aws_iam_role_policy.lambda,
    aws_cloudwatch_log_group.lambda
  ]
}

# Allow Amazon S3 to invoke Lambda when incoming emails arrive.
# Restrict invocation to our S3 bucket and AWS account.
resource "aws_lambda_permission" "s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.moderate.function_name

  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.mail.arn
  source_account = data.aws_caller_identity.current.account_id
}
