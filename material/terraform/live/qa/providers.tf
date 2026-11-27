provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = local.resource_tags
  }
}

provider "aws" {
  alias  = "platform"
  region = local.platform_region

  default_tags {
    tags = local.resource_tags
  }
}
