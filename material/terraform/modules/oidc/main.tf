data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "gitlab_ci" {
  url             = "https://gitlab.kilab-platform.de"
  client_id_list  = ["https://gitlab.kilab-platform.de"]
  thumbprint_list = [var.thumbprint]

  tags = merge(
    {
      Name      = "gitlab-ci-oidc"
      component = "runner-manager"
    },
    var.additional_tags,
  )

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "Wrong account. Expected ${var.account_id}, got ${data.aws_caller_identity.current.account_id}."
    }
  }
}
