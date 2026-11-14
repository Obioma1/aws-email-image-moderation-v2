# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

variable "project_name" {
  description = "Short name used for AWS resources."
  type        = string
  default     = "email-moderation-v2"
}

variable "intake_domain" {
  description = "Dedicated SES subdomain, for example inbox.example.com."
  type        = string
}

variable "approved_email" {
  description = "cPanel mailbox receiving approved image attachments."
  type        = string
}

variable "flagged_email" {
  description = "cPanel mailbox receiving flagged image review notifications and links."
  type        = string
}

variable "moderation_threshold" {
  description = "Minimum confidence percentage for Rekognition moderation labels. Additional visual and text-based review rules are evaluated separately."
  type        = number
  default     = 80
}

variable "link_expiry_seconds" {
  description = "Requested review link lifetime; AWS session expiry can shorten it."
  type        = number
  default     = 3600
}

variable "enable_receiving" {
  description = "Set true only after DNS verification. Activates the SES receipt rule set in London."
  type        = bool
  default     = false
}