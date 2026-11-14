# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

# Create a dedicated CloudWatch log group for the Lambda function.
# The name matches Lambda's default logging destination.
resource "aws_cloudwatch_log_group" "lambda" {
  name = "/aws/lambda/${var.project_name}"

  # Automatically delete log events after 30 days.
  retention_in_days = 30

  tags = {
    Project   = var.project_name
    Component = "LambdaLogging"
    ManagedBy = "Terraform"
  }
}
