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
| M2 | Reliable AI HR Workflow Platform: the AI foundation ([definition and acceptance](m2-reliable-ai-hr-workflow-platform.md); rebaselined 2026-10-20, §7) | Local + CI; accepted on temporary demo hosting (§6) |
| M3 | Workflow Proof (not re-scoped since §7) | Local + CI; temporary demo hosting (§6) |
| M4 | AI Intelligence Hardening & Optimization (provisional; acceptance scope to be defined separately, §7) | Local + CI; temporary demo hosting (§6) |
| M5 | Cloud Activation, Staging Hardening & Production Release | AWS begins here |

**AI foundation = M2. AI refinement and hardening = M4.** AI is part of M2,
and M4 does not introduce it. M2's former non-AI "Workflow Platform"
acceptance model and M4's former "Intelligence Layer" scope are
**superseded** (§7).

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
| External AI processing | Before any external AI provider receives identifiable or customer HR data. This gate governs the data, not whether HeroOS uses AI: AI is part of M2 (§7), so this may first happen in M2. While AI processing uses only local models or synthetic/test data, these may remain pending | PRIV-009, PRIV-010, PRIV-011, PRIV-012, PRIV-021, and PRIV-014 for the provider's approval |
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

M2 is explicitly AI-based. AI is not an optional enhancement to M2: it is part
of the M2 product architecture and acceptance contract.

**Previous plan: SUPERSEDED.** Under the 2026-10-09 plan, M2 "Workflow
Platform" was accepted as a primarily non-AI workflow and Conditions platform,
and controlled AI intelligence was planned for M4 "Intelligence Layer". That
acceptance model and that sequencing are retired. M2 does not have to be
completed without AI first, and M4 is no longer where AI first appears.

**AI foundation in M2, refinement in M4.** M4 does not introduce AI into
HeroOS. It improves the AI capability delivered by M2. Its provisional name is
**M4 — AI Intelligence Hardening & Optimization**: M4 builds on the
production-capable AI foundation delivered in M2 and focuses on improving the
quality, reliability, efficiency and evaluation of HeroOS AI behavior. Its
detailed acceptance scope will be defined separately. Concerns it may take up
include the following; none of them is a committed M4 deliverable yet:

- prompt and orchestration refinement;
- systematic AI evaluations and response-quality measurement;
- comparing models and providers;
- latency and cost optimization;
- optimizing context selection and retrieval quality;
- hallucination and failure analysis;
- better observability and tracing;
- adversarial and prompt-injection testing;
- confidence and uncertainty calibration;
- structured-output reliability;
- conversation-quality improvements;
- model customization or fine-tuning, if the evidence justifies it;
- regression suites for AI behavior.

**AI in M2 is not approval to send data to providers.** These are two separate
questions:

| Question | Answer |
| --- | --- |
| Is AI part of M2? | **Yes.** Decided by this record |
| May identifiable or customer HR data be sent to an external AI provider? | **Not by this record.** The external-AI gate (§4) governs it: PRIV-009 to PRIV-012, PRIV-021, and PRIV-014 for the provider's approval |

M2 may therefore use:
- synthetic and demo data immediately, under the demo-hosting constraints (§6);
- local or private models, where applicable;
- an external provider for identifiable or customer data only once the gate's
  decisions have been made for that provider.

This record approves no vendor. Privacy and tenant-isolation controls are
unchanged.

**Rationale.** JJ's requirement changed between the 13 October and 21 October
2026 discussions. HeroOS must behave as an AI-first HR adviser that identifies
the workflow from the founder's own words. The signed-in product becomes three
areas: Ask HeroOS, Company Blueprint and Company Space. The product direction
recorded on 2026-10-20 is that AI is a core part of M2, and that M4 refines
and hardens it.

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
- **M3.** It keeps its name in §1 and is not re-scoped yet. Its scope is an
  open decision.
- **AI authority.** An AI-based M2 does not mean the AI controls HR decisions.
  AI controls the conversation. Approved HeroOS methodology controls the
  guidance. Deterministic workflow state, Conditions and jurisdiction controls
  remain authoritative. The employer makes the final employment decision.

**Privacy documents (follow-up).** The
[Decision Register](../privacy/decision-register.md),
[JJ Review Packet](../privacy/jj-decision-review-packet.md),
[Third-Party Service Inventory](../privacy/third-party-service-inventory.md) and
[Production Security Gates](../architecture/production-security-gates.md) still
say the external-AI gate may arise in "M4 (Intelligence Layer)". PRIV-021's
traceability row still calls it the "First AI feature (M4 Intelligence
Layer)". That timing text reflects the superseded 2026-10-09 plan. The gate is
triggered by the processing itself, in whichever milestone it happens (§4).
Until those documents are aligned, read "M4" there as "the first milestone that
sends identifiable or customer data to an external AI provider", which may now
be M2. This record changes no privacy decision.

GroqCloud is the language-model provider of the Hannah demo
([Hannah AI demo](../architecture/hannah-ai-demo.md)), which runs on demo
hosting with fictional scenarios. It is not listed in the
[Third-Party Service Inventory](../privacy/third-party-service-inventory.md),
and it is not approved for real employee or customer HR data. Its synthetic
demo use may continue only within the existing constraints (§6, and the demo's
own switch, which production refuses). Recording it in the inventory is an open
governance follow-up. That follow-up does not block M2's AI architecture.

