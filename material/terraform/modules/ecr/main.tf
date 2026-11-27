data "aws_caller_identity" "current" {}

resource "aws_ecr_repository" "renate_lambda" {
  name                 = "renate-lambda"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(
    {
      Name      = "renate-lambda"
      component = "ecr"
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

resource "aws_ecr_lifecycle_policy" "renate_lambda" {
  repository = aws_ecr_repository.renate_lambda.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep last 20 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 20
        }
        action = { type = "expire" }
      },
    ]
  })
}
