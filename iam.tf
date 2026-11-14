# ============================================================
# Project: AWS Email Image Moderation V2
# Author: Obioma Iwuji
# Description: AWS Serverless Email Image Classification,
#              Moderation and Automated Approval/Flagging
# AWS Region: eu-west-2 (London)
# Infrastructure as Code: Terraform
# ============================================================


# Allow only AWS Lambda to assume this execution role.
resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowLambdaAssumeRole"
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project   = var.project_name
    Component = "LambdaExecution"
    ManagedBy = "Terraform"
  }
}

# Grant Lambda only the permissions required for email
# processing, image analysis, notification and logging.
resource "aws_iam_role_policy" "lambda" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [

      # Write application logs to the dedicated CloudWatch log group.
      {
        Sid    = "WriteLambdaLogs"
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },

      # Read incoming emails stored by Amazon SES.
      {
        Sid    = "ReadIncomingEmails"
        Effect = "Allow"

        Action = [
          "s3:GetObject"
        ]

        Resource = "${aws_s3_bucket.mail.arn}/incoming/*"
      },

      # Store and retrieve extracted image attachments.
      {
        Sid    = "ManageExtractedImages"
        Effect = "Allow"

        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]

        Resource = "${aws_s3_bucket.mail.arn}/images/*"
      },

      # Analyse images for moderation labels, general
      # content labels and text.
      {
        Sid    = "AnalyseImagesWithRekognition"
        Effect = "Allow"

        Action = [
          "rekognition:DetectModerationLabels",
          "rekognition:DetectLabels",
          "rekognition:DetectText"
        ]

        Resource = "*"
      },

      # Send moderation results to approved and flagged mailboxes.
      # The sender and recipient addresses are restricted.
      {
        Sid    = "SendModerationNotifications"
        Effect = "Allow"

        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]

        Resource = [
          aws_ses_domain_identity.intake.arn,
          "arn:aws:ses:eu-west-2:${data.aws_caller_identity.current.account_id}:identity/${var.approved_email}",
          "arn:aws:ses:eu-west-2:${data.aws_caller_identity.current.account_id}:identity/${var.flagged_email}"
        ]


        Condition = {
          StringEquals = {
            "ses:FromAddress" = local.sender_email
          }

          "ForAllValues:StringEquals" = {
            "ses:Recipients" = [
              var.approved_email,
              var.flagged_email
            ]
          }
        }
      }
    ]
  })
}
