locals {
  project_name = "heroos"
  environment  = "production"
  name_prefix  = "${local.project_name}-${local.environment}"

  common_tags = {
    Project     = "HeroOS"
    Environment = local.environment
    ManagedBy   = "Terraform"
    Repository  = "HeroOS-HQ/heroos-app"
  }
}
