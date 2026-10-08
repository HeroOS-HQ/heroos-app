# HeroOS Infrastructure

HeroOS AWS infrastructure is managed with Terraform.

## Region

HeroOS V1 uses:

- AWS region: `me-central-1`
- Region name: Middle East (UAE)

## Environments

Terraform roots are separated by environment:

- `environments/staging`
- `environments/production`

Production and staging infrastructure must remain independently managed.

## Naming

AWS resources should follow:

`heroos-<environment>-<resource>`

Examples:

- `heroos-staging-api`
- `heroos-staging-web`
- `heroos-production-api`

## Required Tags

Terraform-managed AWS resources inherit:

- `Project = HeroOS`
- `Environment = staging | production`
- `ManagedBy = Terraform`
- `Repository = HeroOS-HQ/heroos-app`

## Authentication

Do not place AWS access keys or secret keys in Terraform source files.

Human engineering access should use short-lived or federated AWS credentials.

GitHub deployments will use GitHub Actions OIDC rather than long-lived AWS access keys.

## Terraform State

Remote Terraform state will be configured after the HeroOS-owned AWS account exists.

Terraform state files must never be committed to Git.

## Provisioning

Infrastructure is provisioned only when there is an approved deployment requirement.

Do not run `terraform apply` merely to validate infrastructure code.

At the current M1-03 foundation stage, Terraform is initialized and validated locally without creating AWS resources.
