variable "aws_region" {
  description = "AWS region used by the HeroOS staging environment."
  type        = string
  default     = "me-central-1"

  validation {
    condition     = var.aws_region == "me-central-1"
    error_message = "HeroOS V1 staging must use AWS Middle East (UAE), me-central-1."
  }
}
