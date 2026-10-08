# ADR-007: GitHub Actions Authentication to AWS

## Status

Accepted

## Context

HeroOS requires automated deployment from GitHub Actions to AWS.

Long-lived AWS access keys stored in GitHub secrets create unnecessary credential
management and security risk.

HeroOS therefore requires short-lived AWS credentials for CI/CD.

## Decision

GitHub Actions will authenticate to AWS using OpenID Connect (OIDC) and AWS
Security Token Service (STS).

No long-lived AWS access key or AWS secret access key will be stored in GitHub.

The AWS OIDC identity provider will use:

- Provider URL: `https://token.actions.githubusercontent.com`
- Audience: `sts.amazonaws.com`

GitHub Actions deployment jobs will require:

```yaml
permissions:
  contents: read
  id-token: write