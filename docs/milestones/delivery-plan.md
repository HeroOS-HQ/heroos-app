# HeroOS Delivery Plan

**Status:** Current plan (authoritative for milestone sequencing)\
**Owner:** Technical Lead\
**Decision date:** 2026-10-09; M2 rebaselined 2026-10-20 (§7)\
**Related:** [M2 — Reliable AI HR Workflow Platform](m2-reliable-ai-hr-workflow-platform.md),
[M1 Closeout](m1-foundation-security-closeout.md),
[Production Security Gates](../architecture/production-security-gates.md),
[Decision Register](../privacy/decision-register.md),
[JJ Review Packet](../privacy/jj-decision-review-packet.md)

This is the single current statement of milestone sequencing. Other documents
link here instead of repeating it.

## 1. Milestones

| Milestone | Scope | Environment |
| --- | --- | --- |
| M1 | Foundation & Security | **Done** (local + CI) |
| M2 | Reliable AI HR Workflow Platform ([definition and acceptance](m2-reliable-ai-hr-workflow-platform.md); rebaselined 2026-10-20, §7) | Local + CI; accepted on temporary demo hosting (§6) |
| M3 | Workflow Proof (not re-scoped since §7) | Local + CI; temporary demo hosting (§6) |
| M4 | Intelligence Layer (not re-scoped since §7) | Local + CI; temporary demo hosting (§6) |
| M5 | Cloud Activation, Staging Hardening & Production Release | AWS begins here |

M2's former "Workflow Platform" acceptance model is **superseded** (§7).

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
- **CI:** every M1 job keeps running on every pull request and on every push
  to `main` or `dev` (the integration branch, so merges into `dev` are
  verified too): Web, API, Containers, Tenant Isolation, Backup & Restore and
  Privacy Decisions. End-to-End runs only for `main` (pushes and pull
  requests into it); it is retired for `dev`, where `make e2e-check` runs it
  locally when needed. AWS deployment pipelines are M5 work.
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
| External AI processing | Before any external AI provider receives identifiable or customer HR data. Since the M2 rebaseline (§7), this may first happen in M2, which now includes the controlled AI conversation. While AI processing uses only local models or synthetic/test data, these may remain pending | PRIV-009, PRIV-010, PRIV-011, PRIV-012, PRIV-021, and PRIV-014 for the provider's approval |
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

## 6. Decision record: no AWS before M4; temporary demo hosting

**Date:** 2026-10-10

**Decision.** No AWS service, Amazon Cognito included, is used until M4 is
complete. For demonstrations during M2–M4, HeroOS may run on temporary hosting:

| Layer | Service | Notes |
| --- | --- | --- |
| Web | Vercel | Next.js; server-side session; no `NEXT_PUBLIC_*` configuration |
| API | Render | `HEROOS_ENV=staging`: deployed-environment database guards on |
| Database | Supabase PostgreSQL | Alembic schema, RLS, restricted runtime role; Data API disabled |
| Sign-in | A standards-based OpenID Provider | Provider-neutral `oidc` provider ([ADR-003 addendum](../decisions/ADR-003-authentication.md)) |

**Constraints.** Synthetic data only; no production or customer data. Merging
to `main` does not deploy anything; each deployment step needs explicit approval.
The existing development VPS is unaffected.

**Non-effect.** M5 is unchanged: AWS (`me-central-1`) with Cognito, RDS, S3 and
the other managed services. The demo hosting and its identity provider are
temporary and are not carried into Staging or Production.

## 7. Decision record: M2 rebaselined as Reliable AI HR Workflow Platform

**Date:** 2026-10-20 (M2-NEW-01)

**Decision.** M2 is redefined as **Reliable AI HR Workflow Platform**. It is a
signed-in platform where a founder describes an HR situation naturally, and
HeroOS guides the case with approved HeroOS knowledge, Company Blueprint
context and authorized case history. Deterministic workflow state, Conditions,
jurisdiction controls and employment-decision boundaries remain authoritative.
Disciplinary is the end-to-end reference workflow. The definition, acceptance
pillars, Done statement, scope, deferrals and issue sequence are in
[M2 — Reliable AI HR Workflow Platform](m2-reliable-ai-hr-workflow-platform.md).

**Previous plan: SUPERSEDED.** Under the 2026-10-09 plan, M2 "Workflow
Platform" was accepted as a primarily non-AI workflow and Conditions platform,
and controlled AI intelligence was planned for M4 "Intelligence Layer". That
acceptance model is retired. M2 does not have to be completed without AI
first.

**Rationale.** JJ's requirement changed between the 13 October and 21 October
2026 discussions. HeroOS must behave as an AI-first HR adviser that identifies
the workflow from the founder's own words. The signed-in product becomes three
areas: Ask HeroOS, Company Blueprint and Company Space.

**Non-effect.**
- **Earlier work.** The M2-01 to M2-05 engineering, the Hannah AI demo and the
  workspace UI remain valid and become the foundation of the new M2 (inventory:
  [M2 contract §11](m2-reliable-ai-hr-workflow-platform.md#11-what-the-earlier-m2-work-provides)).
  Their documents keep their original milestone label as a historical record.
- **M1 and the architecture.** M1 remains Done. No architecture principle,
  security control or privacy decision changes, and no governance gate's
  trigger or decisions change. §4 now only notes that the external-AI gate may
  first apply in M2.
  [V1 System Architecture §3.4](../architecture/v1-system-architecture.md#34-ai-is-not-the-source-of-hr-truth)
  still governs what AI may do.
- **Hosting and cloud timing.** §3, §5 and §6 are unchanged: local + CI through
  M4, temporary demo hosting with synthetic data only, and AWS from M5.
- **M3 and M4.** They keep their names in §1 but are not re-scoped yet. The
  earlier plan put controlled AI conversation and approved-knowledge guidance
  in M4; for Disciplinary, they are now M2 requirements. What remains in M3 and
  M4 is an open decision.

**Privacy documents.** The [Decision Register](../privacy/decision-register.md),
[JJ Review Packet](../privacy/jj-decision-review-packet.md),
[Third-Party Service Inventory](../privacy/third-party-service-inventory.md) and
[Production Security Gates](../architecture/production-security-gates.md) say
the external-AI gate may arise in "M4 (Intelligence Layer)". The gate is
triggered by the processing itself, in whichever milestone it happens (§4).
Read "M4" there as "the first milestone that sends identifiable or customer
data to an external AI provider", which may now be M2. This record does not
change those documents.

