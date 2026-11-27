locals {
  platform_region = "eu-central-1"

  resource_tags = {
    project       = "digibro"
    env           = "qa"
    owner         = "ki-lab"
    "managed-by"  = "tofu"
    repo          = "digibro-monorepo"
    class         = "internal"
    Kostenstelle  = "500050"
    Kostentraeger = "NCL701"
    Sachkonto     = "7978801"
  }
}
