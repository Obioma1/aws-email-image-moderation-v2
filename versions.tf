# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================

terraform {
  required_version = ">= 1.5.0, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}