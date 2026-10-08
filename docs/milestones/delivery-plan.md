# HeroOS Delivery Plan

**Status:** Current plan (authoritative for milestone sequencing)\
**Owner:** Technical Lead\
**Decision date:** 2026-10-09\
**Related:** [M1 Closeout](m1-foundation-security-closeout.md),
[Production Security Gates](../architecture/production-security-gates.md),
[Decision Register](../privacy/decision-register.md),
[JJ Review Packet](../privacy/jj-decision-review-packet.md)

This is the single current statement of milestone sequencing. Other documents
link here instead of repeating it.

## 1. Milestones

| Milestone | Scope | Environment |
| --- | --- | --- |
| M1 | Foundation & Security | **Done** (local + CI) |
| M2 | Workflow Platform | Local + CI |
| M3 | Workflow Proof | Local + CI |
| M4 | Intelligence Layer | Local + CI |
| M5 | Cloud Activation, Staging Hardening & Production Release | AWS begins here |

HeroOS is **local-first, cloud-ready, cloud-late, but not cloud-last**. The
product is built and verified locally and in CI through M4. AWS activation
starts in M5, once M4 is locally complete and confirmed, and M5 is planned as a
phase with repeated test/fix cycles, not a single deployment at the end.

## 2. M5 sequence

```text
local M4 complete and confirmed
  -> provision AWS (me-central-1)
  -> deploy Staging
  -> activate managed services (RDS, S3, Cognito, Secrets Manager, CloudWatch, ALB/ACM)
  -> full cloud E2E, security and backup/recovery testing
  -> fix -> redeploy -> regression test        (repeated as needed)
  -> founder/pilot acceptance
  -> Production deployment
  -> Production verification
  -> stabilization
```

M5 keeps enough time for several Staging test/fix/redeploy loops before
Production. Every gate in
[Production Security Gates](../architecture/production-security-gates.md) must
pass before production customer data is accepted.

## 3. What stays the same through M4

- **Runtime:** local PostgreSQL 16, the local private-object provider,
  development authentication, structured logging to stdout, and logical
  backup/restore verification on disposable databases.
- **CI:** every M1 job keeps running on every pull request and push to `main`:
  Web, API, Containers, Tenant Isolation, Backup & Restore and Privacy
  Decisions. AWS deployment pipelines are M5 work.
- **Infrastructure:** the M1-03 Terraform scaffold stays a dormant, cloud-ready
  foundation. No AWS resource is created, and the region (`me-central-1`),
  naming, tagging, staging/production separation and GitHub OIDC design
  (ADR-002, ADR-007) are unchanged.
- **Security requirements:** unchanged. Only the milestone that activates the
  AWS controls moved.

## 4. Governance gates by milestone

Pending decisions in the [Decision Register](../privacy/decision-register.md)
gate the milestone where the affected behavior first appears, not M5 alone:

| Gate | Applies when | Decisions |
| --- | --- | --- |
| Deletion | Before M2 introduces any user-facing deletion policy, API or UI | PRIV-020 (and the retention decisions it defers to) |
| External AI processing | Before any external AI provider receives identifiable or customer HR data. This may happen in M4 (Intelligence Layer). If M4 uses only local models or synthetic/test data, these may remain pending | PRIV-009, PRIV-010, PRIV-011, PRIV-012, PRIV-021, and PRIV-014 for the provider's approval |
| Cloud and Production | Before M5 cloud/Production activation | PRIV-006, PRIV-007, PRIV-013, PRIV-014, PRIV-017, PRIV-019, PRIV-022 |

## 5. Decision record: cloud activation moves to M5

**Date:** 2026-10-09

**Decision.** HeroOS remains local + CI through M4. AWS activation starts in M5
after local product completion.

**Previous plan.** M1 was planned and closed with live AWS/Staging activation
in M3 (see the [M1 Closeout](m1-foundation-security-closeout.md), which keeps
that record and carries a post-closeout amendment).

**Rationale.**
- Avoid premature cloud spend.
- Maximize local iteration speed while the workflow and intelligence features
  are built.
- Preserve the cloud-ready architecture defined and tested in M1.
- Deploy once the end-to-end product is worth exercising in managed
  infrastructure.
- Keep enough M5 time for Staging, managed-service integration,
  test/fix/redeploy loops and Production hardening.

**Non-effect.** This changes delivery timing only. M1 architecture, security
controls, tests and acceptance evidence remain valid, and M1 remains complete.
No architecture, security requirement or privacy decision outcome changes.
