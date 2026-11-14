# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

provider "aws" {
  region = "eu-west-2"
}

# Retrieve the AWS account ID for resource policies.
data "aws_caller_identity" "current" {}

# Construct the SES incoming and outgoing email addresses.
locals {
  intake_email = "images@${var.intake_domain}"
  sender_email = "moderation@${var.intake_domain}"
}