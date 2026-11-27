mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "831926590742"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "eu-central-1"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::831926590742:role/mock-ses-lambda"
    }
  }

  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:eu-central-1:831926590742:function:mock-ses-processor"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:eu-central-1:831926590742:mock-ses-alerts"
    }
  }

  mock_resource "aws_ses_domain_dkim" {
    defaults = {
      dkim_tokens = ["tokenone", "tokentwo", "tokenthree"]
    }
  }
}

run "accepts_only_the_official_brochure_alert_mailboxes" {
  command = plan

  variables {
    env_name          = "dev"
    account_id        = "831926590742"
    hosted_zone_id    = "Z0123456789ABCDEF"
    domain_name       = "mail.example.invalid"
    recipient_address = "brochures@mail.example.invalid"
    allowed_senders   = ["sender@example.invalid"]
    alert_emails = [
      "renate@drv-bund.de",
      "ki-reha-anwendungsbetrieb@drv-bund.de",
    ]
  }

  assert {
    condition = [
      for subscription in aws_sns_topic_subscription.email : subscription.endpoint
      ] == [
      "renate@drv-bund.de",
      "ki-reha-anwendungsbetrieb@drv-bund.de",
    ]
    error_message = "The Dev SES brochure topic must subscribe exactly the two official mailboxes."
  }
}

run "rejects_personal_alert_addresses" {
  command = plan

  variables {
    env_name          = "dev"
    account_id        = "831926590742"
    hosted_zone_id    = "Z0123456789ABCDEF"
    domain_name       = "mail.example.invalid"
    recipient_address = "brochures@mail.example.invalid"
    allowed_senders   = ["sender@example.invalid"]
    alert_emails = [
      "person@example.invalid",
      "ki-reha-anwendungsbetrieb@drv-bund.de",
    ]
  }

  expect_failures = [var.alert_emails]
}

run "rejects_an_incomplete_official_mailbox_set" {
  command = plan

  variables {
    env_name          = "dev"
    account_id        = "831926590742"
    hosted_zone_id    = "Z0123456789ABCDEF"
    domain_name       = "mail.example.invalid"
    recipient_address = "brochures@mail.example.invalid"
    allowed_senders   = ["sender@example.invalid"]
    alert_emails      = ["renate@drv-bund.de"]
  }

  expect_failures = [var.alert_emails]
}
