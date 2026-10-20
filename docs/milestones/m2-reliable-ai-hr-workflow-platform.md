# M2 — Reliable AI HR Workflow Platform

**Status:** Current M2 definition and acceptance contract. Recorded 2026-10-20
by M2-NEW-01. It supersedes the 2026-10-09 "M2 — Workflow Platform"
acceptance model (§2)\
**Owner:** Technical Lead\
**Issue:** M2-NEW-01 — Rebaseline M2 as Reliable AI HR Workflow Platform\
**Baseline inspected:** `dev` at `b17e439`\
**Related:** [Delivery Plan](delivery-plan.md) (sequencing; decision record §7),
[V1 System Architecture §3](../architecture/v1-system-architecture.md#3-core-architecture-principles),
[M1 Closeout](m1-foundation-security-closeout.md),
[Decision Register](../privacy/decision-register.md)

This document defines M2, states when it is done, and records what the earlier
M2 work contributes. It changes no product behavior. Linear holds each issue's
scope and status.

## 1. Definition

M2 delivers a reliable signed-in HeroOS platform where a founder can describe
an HR situation naturally and HeroOS uses approved HeroOS knowledge, Company
Blueprint context and authorized case history to guide the case.

AI controls conversational understanding and phrasing.

Deterministic workflow state, Conditions enforcement, jurisdiction controls and
employment-decision boundaries remain authoritative.

The Disciplinary workflow is the end-to-end reference implementation.

M2 is proven when a user can complete a real staging journey involving
natural-language intake, automatic case creation, contextual questioning,
deterministic Guidance / Warning / Block / Expert Review behavior, persistent
case state/history and safe escalation without scripted demo-only responses.

**AI is core to M2.** AI is not an optional enhancement to M2. It is part of
the M2 product architecture and acceptance contract.

M4 does not introduce AI into HeroOS. M4 improves the AI capability delivered
by M2. Its provisional name is "AI Intelligence Hardening & Optimization"
([Delivery Plan §7](delivery-plan.md#7-decision-record-m2-rebaselined-as-reliable-ai-hr-workflow-platform)).

"Staging" in this document means the temporary demo hosting of
[Delivery Plan §6](delivery-plan.md#6-decision-record-no-aws-before-m4-temporary-demo-hosting)
(Vercel, Render, Supabase and a standards-based OpenID Provider). It is not
the AWS Staging environment of M5.

## 2. Why M2 was rebaselined

**Previous acceptance model: SUPERSEDED.** Under the 2026-10-09 plan, M2
("Workflow Platform") was primarily a non-AI workflow and Conditions
implementation. It covered guided structured questions, deterministic intake
and progression, decision records, case history and template previews, each
built and labelled "no AI". Controlled AI intelligence was scheduled for M4
("Intelligence Layer"). That model and that sequencing are retired:
- M2 is no longer accepted against the old model, and it does not have to be
  completed without AI first.
- AI is a core part of M2.
- M4 is no longer where AI first appears.

**Current requirement.** JJ's requirement changed between the 13 October and
21 October 2026 discussions. HeroOS must now behave as an AI-first HR adviser:

- The founder explains an HR situation naturally and doesn't select an HR
  category or workflow.
- HeroOS determines the relevant workflow and context, and asks only the
  follow-up questions it needs.
- HeroOS uses approved Playbooks, the Conditions Library, the Company Blueprint
  and authorized case history.
- Deterministic workflow and Conditions logic remain authoritative. The AI
  doesn't make employment decisions on its own.
- Unsupported or unsafe cases warn, block or escalate.
- The employer remains responsible for the final employment decision.

The signed-in product now has three primary areas: **Ask HeroOS**,
**Company Blueprint** and **Company Space**. The old dashboard is not part of
the primary experience. Disciplinary is the reference workflow. The staging
demonstration for Michael is intended as M2's final external proof (§9).

**Earlier work is the foundation, not waste.** M2-01 to M2-05, the Hannah AI
demo and the workspace UI built the engine, records and controls this
definition depends on (§11). Their documents keep the label "M2 — Workflow
Platform": it accurately records when, and under which plan, they were built.

## 3. Product and safety boundaries

An AI-based M2 does not mean that the AI controls HR decisions.

> AI controls the conversation. Approved HeroOS methodology controls the
> guidance. Deterministic workflow state, Conditions and jurisdiction controls
> remain authoritative. The employer makes the final employment decision.

AI may understand, extract, propose, phrase and ask. It may not bypass
deterministic safeguards, and it may not approve employment actions on its
own.

**AI may:**

- understand natural language;
- identify the likely workflow intent;
- extract and propose facts;
- propose a case title;
- decide conversational phrasing;
- decide which missing information to ask for;
- explain approved guidance.

**AI must not:**

- invent HR or legal rules;
- bypass Conditions;
- bypass jurisdiction requirements;
- authorize a prohibited workflow transition;
- choose an employment sanction on its own;
- approve a dismissal on its own;
- treat unsupported content as approved;
- silently use open-web or general-model legal knowledge as authority.

These boundaries refine
[V1 System Architecture §3.4](../architecture/v1-system-architecture.md#34-ai-is-not-the-source-of-hr-truth)
("AI is not the source of HR truth"), which still applies. What the AI extracts
or proposes stays a proposal. The deterministic engine decides what is stored
as a fact, whether a transition is allowed, and whether a Condition fired.

These existing controls carry over unchanged:

- Membership authorization and tenant isolation on every route.
- Jurisdiction separation: no UAE Federal / MOHRE guidance on a DIFC case, and
  no DIFC guidance on a UAE Federal case.
- Fail-closed behavior when rules, content or the jurisdiction are missing.
- No HR content in logs.
- The governance gates of [Delivery Plan §4](delivery-plan.md#4-governance-gates-by-milestone).

## 4. Acceptance pillars

| # | Pillar | Accepted when |
| --- | --- | --- |
| 1 | AI conversation | A founder describes an HR problem naturally, and HeroOS understands it without the founder choosing a workflow, case category, case title or disciplinary stage |
| 2 | Controlled intelligence | For HR workflow guidance, the AI uses only approved HeroOS sources and authorized company and case context. It doesn't invent legal requirements, and it doesn't silently fall back on general model knowledge when HeroOS material is insufficient |
| 3 | Deterministic safety | Workflow and Conditions logic control material outcomes: Normal Guidance, Warning, Block and Expert Review. The LLM doesn't decide whether a deterministic condition fired |
| 4 | Persistent case | HeroOS creates the case automatically, proposes its name, and stores the relevant facts, the workflow state and the case history. The founder can leave the case and reopen it |
| 5 | Company context | The Company Blueprint supplies real company context that the conversation uses. Relevant company information doesn't exist only as mock UI |
| 6 | Reliable staging | JJ can independently sign in, use Ask HeroOS, complete the agreed Disciplinary demo journey, navigate away and return, reopen the case and see the correct persisted state and history |

## 5. Definition of Done

> M2 is Done when JJ can sign into staging as a founder, describe a
> disciplinary HR situation naturally, and HeroOS reliably carries the case
> through approved knowledge, contextual questioning, deterministic safety
> rules, persistent case state and real escalation behavior without relying on
> scripted demo-only responses.

All six pillars must hold together, on staging. M2 is **not** Done because AI
chat works, because demo screenshots exist, or because Disciplinary screens
have been built.

## 6. In scope

**AI (core to M2):**

- Natural-language Ask HeroOS, as the real signed-in experience.
- AI-assisted identification of intent and workflow.
- AI-assisted proposal of the case title.
- AI-assisted extraction and proposal of facts.
- Contextual follow-up questions.
- Company Blueprint context.
- Authorized case-history context.
- Approved HeroOS knowledge context, through an approved knowledge runtime.
- AI-generated wording of user-facing guidance. The AI phrases it; approved
  methodology supplies the substance.
- A controlled AI gateway.

**Deterministic and product foundations:**

- Deterministic workflow transitions.
- Deterministic Conditions enforcement.
- Jurisdiction isolation.
- Persistent cases: their facts, workflow state and history.
- The four outcomes: Normal Guidance, Warning, Block and Expert Review.
- The Expert Review MVP lifecycle.
- Disciplinary as the end-to-end reference workflow.
- A real Company Blueprint.
- A real Company Space.
- Safe, supported document actions.

**Acceptance:**

- A real staging acceptance journey.
- The Michael demonstration as the final external proof.

## 7. Deferred from M2

None of these is an M2 acceptance requirement. Existing roadmap references to
them stay where they are.

- Arabic and right-to-left layout.
- Switching between dark and light themes.
- A future analytics dashboard, and dashboard KPIs.
- Final pricing and billing.
- Final subscription and package names.
- The final Expert Review usage cap, including the possible "50 questions"
  limit that has been discussed.
- A sophisticated copilot between HeroOS administrators and the AI expert.
- A full consultancy CRM or workflow.
- Consultancy payments and invoicing.
- Meeting or video integration.
- Autonomous, unrestricted web research.
- Production Probation and Recruitment workflows. Both remain in the V1 scope
  ([README](../../README.md#v1-scope)); only their production workflows are
  outside M2.
- Advanced Hannah animation.
- Retention and deletion behavior that is still undecided.

## 8. Content, jurisdiction and governance limits

- **Content under review.** Some HeroOS source material is still under legal or
  content review. Rules still under review are tagged
  "Provisional: not legal advice" and are never presented as approved
  ([Disciplinary Intake §2](../architecture/disciplinary-intake.md#2-rules-and-their-content)).
- **Only approved content becomes guidance.** A Conditions Library row does not
  automatically become production guidance; JJ approves the content. The
  repository already loads approved, versioned and pinned private content for
  rules
  ([Workflow Progression §3](../architecture/workflow-progression.md#3-private-rule-bundles))
  and templates
  ([Document Templates §2](../architecture/document-templates.md#2-the-template-bundle-appdocumentsbundlepy)).
  The five intake rules still in code are development content, not legally
  approved
  ([Disciplinary Intake §8](../architecture/disciplinary-intake.md#8-open-decisions-jj)).
- **Jurisdiction isolation.** UAE Federal / MOHRE and DIFC guidance never mix.
  Another jurisdiction's rules are never used as a substitute
  ([Disciplinary Intake §4](../architecture/disciplinary-intake.md#4-jurisdiction-routing)).
- **Unsupported means stop or escalate.** Where HeroOS has no approved content
  for a situation, it stops or escalates. It never invents guidance.
- **No hard-coded commercial limits.** Expert Review usage limits are not
  decided and are not built into the product.
- **Fictional data on staging.** The temporary demo hosting holds synthetic data
  only ([Delivery Plan §6](delivery-plan.md#6-decision-record-no-aws-before-m4-temporary-demo-hosting)),
  so the M2 acceptance journey uses fictional scenarios (§8.1).
- **No user-facing deletion** before PRIV-020 is decided (Delivery Plan §4).
- **Engineering doesn't settle HR or legal questions.** Open content and legal
  questions go to JJ.

### 8.1 AI, data and providers

Whether M2 uses AI and whether real HR data may go to an external provider are
separate questions:

| Question | Answer |
| --- | --- |
| Is AI part of M2? | **Yes.** It is decided and part of the acceptance contract (§1) |
| May identifiable or customer HR data be sent to an external AI provider? | **Only after the external-AI gate:** PRIV-009 to PRIV-012, PRIV-021, and PRIV-014 for that provider ([Delivery Plan §4](delivery-plan.md#4-governance-gates-by-milestone)). Rebaselining M2 approves no vendor |

M2 may use:
- synthetic and demo data immediately;
- local or private models, where applicable;
- approved external providers, once the relevant governance decisions are met.

Privacy and tenant-isolation controls are unchanged.

**GroqCloud** is the language-model provider of the Hannah demo
([Hannah AI demo](../architecture/hannah-ai-demo.md)).
- **Current use:** fictional scenarios on the temporary demo hosting only,
  behind `HEROOS_HANNAH_DEMO_ENABLED`, which production refuses.
- **Inventory:** it is not listed in the
  [Third-Party Service Inventory](../privacy/third-party-service-inventory.md).
- **Approval:** it is not approved for real employee or customer HR data.
  Choosing M2's provider for such data is part of PRIV-009 and PRIV-014.
- **What may continue:** its synthetic demo use, within the existing demo
  constraints only.
- **Follow-up:** recording it in the inventory is a governance follow-up
  (§12). That follow-up doesn't block M2's AI architecture.

## 9. The Michael demonstration: acceptance proof

**The demo is evidence. The M2 implementation is the deliverable.**

The Michael demonstration is intended as M2's final external proof. A scripted
demo that works does not complete M2. The demonstration must run on the real,
integrated staging system, through the same code paths JJ uses independently
(pillar 6), with no response prepared for the demo.

The golden journey below is the acceptance target. M2-NEW-01 implements none
of it.

1. JJ signs in.
2. Ask HeroOS is the primary workspace.
3. JJ enters a natural HR situation.
4. HeroOS understands it without a workflow being selected.
5. A real case is created automatically.
6. Company Blueprint context is reused.
7. HeroOS asks focused follow-up questions.
8. Conditions produce a real outcome that the user can see.
9. A Warning is demonstrated.
10. A Block is demonstrated.
11. Expert Review can be demonstrated.
12. The Case Status is real.
13. The case history persists.
14. JJ can leave the case and reopen it.
15. Changes to the Blueprint persist.
16. Company Space reflects the real company and access state.

## 10. Execution sequence

| Issue | Title |
| --- | --- |
| M2-NEW-01 | Rebaseline M2 as Reliable AI HR Workflow Platform |
| M2-NEW-02 | Promote Approved HeroOS UX into the Real Signed-In App |
| M2-NEW-03 | Make Company Blueprint Real and Usable by HeroOS |
| M2-NEW-04 | Build the Approved Knowledge Runtime |
| M2-NEW-05 | Build the Controlled AI Conversation Gateway |
| M2-NEW-06 | Connect AI Conversation to Workflow + Conditions Engine |
| M2-NEW-07 | Complete Persistent Case Lifecycle + Case Status |
| M2-NEW-08 | Finish Disciplinary as the End-to-End Reference Workflow |
| M2-NEW-09 | Implement Expert Review MVP + HeroOS Expert Response Flow |
| M2-NEW-10 | Make Company Space Use Real Access + Real Company State |
| M2-NEW-11 | Michael Demo Readiness + M2 Final Acceptance |

This table records the agreed order only. Each issue's scope is defined in
Linear. M2-NEW-01 created and changed no Linear issue.

## 11. What the earlier M2 work provides

This inventory was checked against the repository at `dev` `b17e439`. No
deployed environment was inspected.

### 11.1 Implemented and reusable

| Capability | Evidence |
| --- | --- |
| Authentication, Membership authorization, trusted Company context, the `company_admin` role | `app/auth/`, `app/tenancy/`; [ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md), [ADR-010](../decisions/ADR-010-company-registration-and-administrators.md) |
| Tenant isolation for every workflow table: scoped repositories, RLS `tenant_isolation`, a restricted runtime role | [Tenant Isolation §9](../architecture/tenant-isolation.md#9-contract-for-future-private-entities-m2-and-later); `tests/tenant_isolation/` |
| Cases, workflow instances and versioned workflow definitions (Disciplinary v1 and v2, with declared compatibility) | `app/workflows/definition.py`; migration D1; [Workflow Case Foundation](../architecture/workflow-foundation.md) |
| Append-only, versioned case facts; idempotent saves; optimistic concurrency under an instance lock | [Workflow Case Foundation §2–4](../architecture/workflow-foundation.md#2-model) |
| Deterministic intake Conditions: typed rules, three-valued logic, warn / block / escalate, and the rule-set version and digest stored with every evaluation | `app/workflows/conditions.py`, `app/workflows/intake.py`; migration D2; [Disciplinary Intake §2](../architecture/disciplinary-intake.md#2-rules-and-their-content) |
| Jurisdiction routing and isolation, from the Company's operator-confirmed employment jurisdiction | `app/companies/jurisdiction.py`; [Disciplinary Intake §4](../architecture/disciplinary-intake.md#4-jurisdiction-routing) |
| Progression engine: `ESCALATE > BLOCK > WARN > ALLOW`, engine gates, escalations that stay in force when answers change, refused transitions recorded | `app/workflows/progression/`; migration D3; [Workflow Progression §2](../architecture/workflow-progression.md#2-the-engine-appworkflowsprogression) |
| Private, pinned, fail-closed content bundles for rules and templates, with validation tools | `app/workflows/progression/bundle.py`, `app/documents/bundle.py`, `scripts/rule_bundle.py`, `scripts/template_bundle.py` |
| Employer decision records that never authorize a step, with correction chains | `app/workflows/decisions.py`; migration D4; [Employer Decisions §2](../architecture/workflow-decisions.md#2-a-record-is-not-an-authorization) |
| A unified case history, composed from append-only records | `app/workflows/timeline.py`; [Employer Decisions §4](../architecture/workflow-decisions.md#4-the-unified-case-history) |
| Template eligibility and watermarked previews (nothing stored or issued); an offline Word converter | `app/documents/`, `scripts/template_import.py`; [Document Templates](../architecture/document-templates.md) |
| An AI provider interface, a server-side key, usage ceilings, a reply check and no write path (from the Hannah demo) | `app/assistant/`; [Hannah AI demo](../architecture/hannah-ai-demo.md) |
| Founder self-registration and onboarding; the Company Blueprint record and API (`GET` and `PATCH /companies/{id}/blueprint`) | `app/api/onboarding.py`, `app/api/companies.py`; [ADR-010](../decisions/ADR-010-company-registration-and-administrators.md) |
| An end-to-end harness on the real web app, API and PostgreSQL, and a synthetic Disciplinary journey (local and CI only) | `make e2e-check`, `e2e/suites/`, `make demo-synthetic`; [Synthetic Founder Demo](../operations/synthetic-founder-demo.md) |

The engine's decisions already correspond to the M2 outcomes: ALLOW is Normal
Guidance, WARN is Warning, BLOCK is Block, and ESCALATE is Expert Review (today
a "specialist review" hold).

### 11.2 Partial: needs integration

| Area | What exists | Gap for M2 |
| --- | --- | --- |
| AI conversation | The Hannah demo: a chat on the case page, through GroqCloud (classification: §8.1) | The model receives only a fixed instruction and the chat turns: no Blueprint, no case facts and no approved knowledge. The turns live in browser memory only, and the chat never writes. It is off unless `HEROOS_HANNAH_DEMO_ENABLED` is set, and production refuses it |
| Case creation | `POST /companies/{id}/workflows/{key}/cases` | The founder has to choose Disciplinary and type the case title |
| Case status | Derived on every read from evaluations and progress events | A case can't be closed; there is no end-of-case lifecycle |
| Company Blueprint | Stored fields: legal name, primary jurisdiction, industry, employee count, licensing location and authority, and the operator-confirmed employment jurisdiction. The deterministic jurisdiction routing uses them | Not used as AI context. Any field in the approved Blueprint design that this schema lacks needs a migration |
| Expert Review outcome | An escalation holds the case for specialist review. The hold can't be released by changed answers, and the history records it | No ticket, expert, response or release exists. The UI says HeroOS doesn't offer expert review yet |
| Disciplinary content | The v2 intake definition; five intake rules in code, two of them provisional; the generic progression engine | No approved rule or template bundle exists in any environment, only fictional test bundles. DIFC cases have no screening or program and stay on hold |
| Signed-in UI | A company frame with Dashboard, Company Blueprint (`/settings`), HR Services and Cases, plus "Team & Access" shown as coming soon. A three-column case page with a Hannah tab | The Ask HeroOS, Company Blueprint and Company Space structure is not in the app. The approved signed-in design is not in the repository yet |
| Staging | Temporary demo hosting ([Delivery Plan §6](delivery-plan.md#6-decision-record-no-aws-before-m4-temporary-demo-hosting)) | As last recorded, no rule or template bundle is installed and the sensitive screening is disabled, so a Disciplinary intake can't be completed there ([Synthetic Founder Demo §4](../operations/synthetic-founder-demo.md#4-what-it-proves-and-what-it-doesnt), [Disciplinary Intake §7.1](../architecture/disciplinary-intake.md#71-staging-deployment-record-2026-10-16)) |

### 11.3 Not yet implemented

- Ask HeroOS as the signed-in home: natural-language entry without choosing a
  workflow.
- Identifying the workflow and intent from natural language, proposing
  extracted facts to the deterministic engine, and proposing case titles.
- An approved knowledge runtime. No Playbook or Conditions Library content is
  served at run time, and the Hannah instruction deliberately contains none.
- A controlled AI gateway connected to the workflow and Conditions engine.
- A persisted conversation.
- The Expert Review MVP and the HeroOS Expert response flow.
- Company Space with real access state. The API has no route that lists a
  Company's people.
- Closing a case.
- Releasing a specialist-review hold. No release exists, and who may release a
  hold is a JJ decision.

### 11.4 Unknown: needs verification

- **What staging runs now:** revisions, schema contract and settings. The
  repository's last staging deployment record is for M2-02 (2026-10-16). The
  M2-03, M2-04 and M2-04C documents still say "not deployed", which may be out
  of date. Check this read-only before M2-NEW-11.
- **Whether the Hannah demo is enabled and configured on staging.** Deployed
  configuration is not in the repository.
- **The status of JJ's private rule and template content.** By design, it is
  kept outside this public repository.
- **How reliably the model follows its instruction.** This is checked only
  live, with fictional scenarios
  ([Hannah AI demo](../architecture/hannah-ai-demo.md#hannahs-behaviour-v11-refined-in-v11a-and-v12)).

## 12. Open questions

**For JJ:**

1. Which content may run on staging for the acceptance journey and the Michael
   demonstration? The options are approved private bundles (these need content
   approval, legal review and a deployment decision) or the fictional test
   bundles (announced as synthetic on every case they serve).
2. May the sensitive screening run in `synthetic_demo` mode on staging? While it
   is disabled, no Disciplinary intake can be completed there.
3. Who may release an Expert Review hold, and how?
   ([Disciplinary Intake §8](../architecture/disciplinary-intake.md#8-open-decisions-jj),
   [Workflow Progression §8](../architecture/workflow-progression.md#8-open-decisions-jj-and-technical-lead))
4. Which knowledge sources (Playbooks, Conditions Library rows) are approved
   for runtime use, for each jurisdiction?

**For the Technical Lead and JJ:**

5. What is the scope of M3? M4 is provisionally AI Intelligence Hardening &
   Optimization; its detailed acceptance scope will be defined separately
   ([Delivery Plan §7](delivery-plan.md#7-decision-record-m2-rebaselined-as-reliable-ai-hr-workflow-platform)).
6. Three governance follow-ups are open. They don't block M2's AI
   architecture, and no privacy decision changes:
   - **Timing text.** The privacy documents' external-AI timing text still
     says "M4 (Intelligence Layer)": the
     [Decision Register](../privacy/decision-register.md),
     [JJ Review Packet](../privacy/jj-decision-review-packet.md),
     [Third-Party Service Inventory](../privacy/third-party-service-inventory.md) and
     [Production Security Gates](../architecture/production-security-gates.md).
     It should be aligned to M2.
   - **GroqCloud.** It should be recorded in the Third-Party Service Inventory
     as a demo-only provider that is not approved for real HR data (§8.1).
   - **Technical facts.** The Decision Register's AI packets still state that
     no AI integration exists in the code. The Hannah demo is one.
