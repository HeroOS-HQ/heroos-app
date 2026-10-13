# ADR-002 — AWS Infrastructure and Environment Architecture

**Status:** Accepted  
**Date:** 2026-10-08  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline

## Context

HeroOS V1 requires a production architecture that is:

- secure
- maintainable by a small engineering team
- cost-conscious
- suitable for sensitive HR data
- deployable within the V1 delivery schedule
- able to support Development, Staging and Production
- capable of supporting future workflow growth
- owned by HeroOS rather than by an individual developer

HeroOS does not currently require Kubernetes, a large distributed platform,
or independently deployed microservices.

The production platform must support:

- Next.js
- FastAPI
- PostgreSQL
- private document storage
- managed authentication
- secrets management
- monitoring/logging
- backups
- controlled background/orchestration workloads

---

## Decision

HeroOS V1 will use AWS as the primary production cloud platform.

The primary AWS region will be:

`me-central-1` — Middle East (UAE)

The initial production architecture will use:

| Capability | AWS Service |
|---|---|
| Container runtime | Amazon ECS on AWS Fargate |
| Container registry | Amazon ECR |
| Public HTTPS entry | Application Load Balancer |
| DNS | Route 53 |
| TLS certificates | AWS Certificate Manager |
| Authentication | Amazon Cognito |
| Relational database | Amazon RDS for PostgreSQL |
| Object/document storage | Amazon S3 |
| Secrets | AWS Secrets Manager |
| Encryption keys where required | AWS KMS |
| Logs and metrics | Amazon CloudWatch |
| Technical orchestration | AWS Step Functions where justified |
| Transactional email | Amazon SES when required |
| Network isolation | Amazon VPC + Security Groups |
| Infrastructure as Code | Terraform |

HeroOS business and workflow state remains authoritative in PostgreSQL.

AWS Step Functions is not the source of truth for HR workflow state.

---

## Region

The default V1 production region is:

`me-central-1`

This places the primary HeroOS AWS application infrastructure in the UAE.

The following major V1 services required by the current architecture are
available in this region:

- ECS / Fargate
- RDS
- Cognito
- S3
- Secrets Manager
- CloudWatch
- Step Functions
- ECR
- Route 53 / ACM integration where applicable

Hosting the primary application in the UAE does not by itself guarantee that
all HeroOS data remains in the UAE.

External providers, especially AI, monitoring, email or support services, may
process data in other jurisdictions.

Cross-border and provider-processing decisions are therefore tracked
separately in the Privacy & Security Decision Register.

---

## High-Level AWS Topology

```text
                         Internet
                            |
                            v
                       Route 53
                            |
                            v
                           TLS
                           ACM
                            |
                            v
                 Application Load Balancer
                     /              \
                    /                \
                   v                  v
          Next.js ECS Service   FastAPI ECS Service
                Fargate              Fargate
                    \                  /
                     \                /
                      \              /
                       v            v
                       Application Layer
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
       RDS PostgreSQL    Private S3      Secrets Manager
             |
             |
             +----------> Audit/Application State

FastAPI
   |
   +----------> Cognito validation
   |
   +----------> CloudWatch
   |
   +----------> Step Functions
   |               |
   |               +--> bounded async/retry jobs
   |
   +----------> Approved external AI provider
   |
   +----------> SES when required
```
