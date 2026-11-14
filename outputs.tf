# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

# DNS records required for Amazon SES domain verification,
# DKIM authentication and inbound email delivery.
# Add these records at the authoritative DNS provider.
output "dns_records" {
  description = "DNS records required to configure Amazon SES."

  value = concat(
    [
      {
        type     = "TXT"
        name     = "_amazonses.${var.intake_domain}"
        value    = aws_ses_domain_identity.intake.verification_token
        priority = null
      },
      {
        type     = "MX"
        name     = var.intake_domain
        value    = "inbound-smtp.eu-west-2.amazonaws.com"
        priority = 10
      }
    ],
    [
      for token in aws_ses_domain_dkim.intake.dkim_tokens : {
        type     = "CNAME"
        name     = "${token}._domainkey.${var.intake_domain}"
        value    = "${token}.dkim.amazonses.com"
        priority = null
      }
    ]
  )
}

# Email address that receives images for moderation.
output "intake_email" {
  description = "Email address used to submit images for moderation."
  value       = local.intake_email
}

# Verified SES sender address for moderation notifications.
output "sender_email" {
  description = "Email address used to send moderation results."
  value       = local.sender_email
}

# cPanel mailbox receiving approved images.
output "approved_email" {
  description = "Destination mailbox for approved image attachments."
  value       = var.approved_email
}

# cPanel mailbox receiving flagged image notifications.
output "flagged_email" {
  description = "Destination mailbox for flagged image review notifications."
  value       = var.flagged_email
}

# Name of the private S3 storage bucket.
output "bucket_name" {
  description = "S3 bucket storing incoming emails and extracted images."
  value       = aws_s3_bucket.mail.id
}

# Name of the deployed AWS Lambda function.
output "lambda_function_name" {
  description = "Lambda function responsible for email image moderation."
  value       = aws_lambda_function.moderate.function_name
}

# CloudWatch log group used for Lambda execution logs.
output "cloudwatch_log_group" {
  description = "CloudWatch log group for Lambda monitoring."
  value       = aws_cloudwatch_log_group.lambda.name
}
