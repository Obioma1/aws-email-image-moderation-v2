# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

# Verify the dedicated email intake subdomain with Amazon SES.
# The main domain continues to use cPanel for normal email.
resource "aws_ses_domain_identity" "intake" {
  domain = var.intake_domain
}

# Generate DKIM records for authenticating outgoing emails.
# DNS records will be published through the domain's DNS provider.
resource "aws_ses_domain_dkim" "intake" {
  domain = aws_ses_domain_identity.intake.domain
}

# Create an SES receipt rule set for incoming moderation emails.
resource "aws_ses_receipt_rule_set" "images" {
  rule_set_name = var.project_name
}

# Receive emails sent to the dedicated intake address.
# The rule is enabled only after DNS verification is complete.
resource "aws_ses_receipt_rule" "images" {
  count = var.enable_receiving ? 1 : 0

  name          = "store-incoming-image-emails"
  rule_set_name = aws_ses_receipt_rule_set.images.rule_set_name

  recipients = [local.intake_email]

  enabled = true

  # Enable SES spam and virus scanning.
  scan_enabled = true

  # Store received emails under the incoming/ S3 prefix.
  s3_action {
    bucket_name       = aws_s3_bucket.mail.id
    object_key_prefix = "incoming/"
    position          = 1
  }

  # Ensure S3 permissions and Lambda notifications exist first.
  depends_on = [
    aws_s3_bucket_policy.ses,
    aws_s3_bucket_notification.incoming
  ]
}

# Activate the receipt rule set after receiving is enabled.
# Only one SES receipt rule set can be active per AWS region.
resource "aws_ses_active_receipt_rule_set" "images" {
  count = var.enable_receiving ? 1 : 0

  rule_set_name = aws_ses_receipt_rule_set.images.rule_set_name

  depends_on = [
    aws_ses_receipt_rule.images
  ]
}
