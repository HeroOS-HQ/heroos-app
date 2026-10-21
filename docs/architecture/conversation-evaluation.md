# Ask HeroOS: deterministic conversation evaluation (M2-NEW-06)

**Status:** implemented and verified locally and in CI with synthetic content and a scripted model. It isn't deployed or activated anywhere: no execution profile is installed in any environment, so the checks report themselves unavailable everywhere (§10).\
**Owner:** Technical Lead\
**Milestone:** [M2 — Reliable AI HR Workflow Platform](../milestones/m2-reliable-ai-hr-workflow-platform.md), issue M2-NEW-06\
**Related:** [ai-gateway.md](ai-gateway.md) (M2-NEW-05, the conversation), [knowledge-runtime.md](knowledge-runtime.md) (M2-NEW-04, the only HR/legal authority), [workflow-progression.md](workflow-progression.md) (the rule bundle and predicate engine), [disciplinary-intake.md](disciplinary-intake.md) (the intake rules)

> **The language model never determines a HeroOS outcome. It proposes understanding and phrases a response. The deterministic backend determines the outcome.**

> **A Condition result and a requested action's availability are separate concepts.**

## 1. What it adds

M2-NEW-05 understood the founder's situation and answered from approved knowledge, but decided nothing. M2-NEW-06 adds the deterministic layer between understanding and wording:

```
FOUNDER NATURAL LANGUAGE
  -> M2-NEW-05 understanding (closed catalog + evidence check)
  -> fact trust: PROPOSED -> ESTABLISHED_CONVERSATIONAL -> ENGINE_TRUSTED
  -> M2-NEW-04 knowledge context
  -> one immutable execution snapshot (knowledge + definition + rule bundle + execution profile)
  -> generic evaluator: Condition evaluations, action evaluations, review requirements,
     missing requirements, cautions
  -> business disposition per step: ALLOW / WARN / UNKNOWN / BLOCK / ESCALATE
  -> one presentation: Guidance / Warning / Block / Expert Review (server-owned card)
  -> server-constrained safe next step
  -> the model phrases it (and only phrases it)
  -> grounding + reply safety + contradiction checks
  -> Ask HeroOS
```

Code: `apps/api/app/evaluation/` (domain), its use in `app/assistant/gateway/service.py`, the browser contract in `app/api/gateway.py`, the card in `apps/web/src/components/ask/ask-conversation.tsx`.

**Still ephemeral.** No Case is created. Nothing is stored: not the conversation, the facts, the evaluation, a pathway, a stage, a submission, a progress event, a decision, a document or an Expert Review. There is no migration (the schema contract is unchanged). M2-NEW-07 owns durable state.

## 2. Source-of-truth hierarchy

1. **The current normalized M2-NEW-04 runtime** (the installed knowledge bundle) is the only HR/legal authority: Conditions, their `enforcement_status`, `citation_status` and `action_policy`, options and their per-jurisdiction availability, guards, quarantine, engine links. The evaluation never reads raw sources, templates, the compile mapping, audit reports or older analyses, and it never reinterprets a source conflict.
2. **The rule bundle** (`heroos.rule-bundle/1`, private) owns every executable predicate and its approved wording.
3. **The execution profile** (`heroos.execution-profile/1`, private) owns only compatibility and explicit bindings (§4). It is not a rules source.
4. **Public code** owns the generic engine, the jurisdiction gate, the precedence, and generic platform wording (labels, errors, safe-next-step texts).

## 3. Execution coverage categories

Every Condition of a workflow gets exactly one category when the snapshot is built (`snapshot.categorize`; the audit is `coverage_matrix`):

| Category | Meaning | In a conversation |
| --- | --- | --- |
| `executable` | An explicit, verified binding to an executor's rule | The rule runs on ENGINE_TRUSTED facts: fired / not fired / unknown; or `unavailable` when its inputs can't be collected here (privacy) |
| `guard_only` | A server-owned rule already represents it whatever the facts: the jurisdiction gate (the global routing precondition), or the approved availability of every decision it is linked to (a Condition that escalates a decision the runtime already routes to review) | Never fires as a Condition; the gate or the availability decides |
| `question_only` | It names what matters, but nothing executable can say it fired | Never claims it fired; shapes questions; a requested step it guards stays `unknown` (never clear) |
| `not_enforced` | The runtime says it never executes | No effect at all (no caution, no hold, no question priority) |
| `quarantined` | The runtime withholds it | No effect; binding it is refused |

`guard_only` is derived, never declared: a Condition is subsumed only if every option linking it, in every jurisdiction of its scope, is held at least as strongly (`review_required` ≥ escalate ≥ block; `not_available` ≥ block).

## 4. The execution profile (`heroos.execution-profile/1`)

```json
{"schema": "heroos.execution-profile/1", "profile": "<id>", "version": "<v>",
 "provenance": "synthetic" | "private", "approval": "development" | "approved",
 "workflows": [{
   "workflow": "<key>",
   "knowledge_runtime_digest": "<sha256 of the M2-NEW-04 runtime section>",
   "definition_version": 2,
   "rule_bundle": {"bundle": "<id>", "version": "<v>", "digest": "<content sha256>"} | null,
   "executors": [{"executor": "intake", "version": "<rule set>", "digest": "<sha256>"},
                 {"executor": "rule_bundle"}],
   "pathway_ownership": "ai_candidate_only" | "employer_confirmation_required" | "deterministic" | "none",
   "bindings": [{"condition": "<Condition id>", "executor": "intake" | "rule_bundle", "rule": "<rule key>"}],
   "covered_actions": [{"action": "<option id>",
                        "prerequisites": {"employee_response": "<rule key>",
                                          "completed_investigation": "<rule key>"}}]}]}
```

The schema is exact: there is no field for wording, a threshold, guidance, a trigger or a predicate. Loading (`load_execution_profile`) is fail-closed like every bundle: SHA-256 pin, strict schema, no duplicate keys, production refuses synthetic or development profiles. A real profile names private Condition ids and stays private (git-ignored names, never committed). `approval: approved` is generic: who may approve what is in §14.1.

**Explicit bindings only.** Nothing is ever bound because a Condition "sounds like" a rule:

- `intake` bindings must equal an M2-NEW-04 engine link exactly (reused, not restated), to an intake rule with a typed predicate. The routing rule reads a Case's persisted confirmation, so it isn't executed on a conversation: the jurisdiction gate represents it (§7).
- `rule_bundle` bindings name a conversation rule of the paired rule bundle, present in every jurisdiction of the Condition's scope.
- Every binding must agree with its Condition: the same initial action, the same follow-up (action and `when`), and a review status that matches (`provisional` ⇔ `needs_legal_review`). A `not_enforced` or quarantined Condition can't be bound.
- A **covered** action is one whose deterministic coverage is complete: every active Condition linked to it where it is `supported` is executable or guard-only, and each mandatory prerequisite the approved option flags (`requires_employee_response`, `requires_completed_investigation`) is bound to a prerequisite rule. Only a covered action can ever be `allow`.

## 5. Version compatibility (fail closed)

`build_snapshot` checks, per workflow, that the profile approves exactly the installed artifacts together: the knowledge runtime digest, the definition version, the rule bundle id, version and content digest (and the bundle serving that definition), every executor's identity, every binding and every covered action. Any mismatch makes that workflow's evaluation **unavailable** with a fixed code (`knowledge_digest_mismatch`, `definition_version_mismatch`, `rule_bundle_mismatch`, `executor_version_mismatch`, `unknown_rule`, `action_mismatch`, `follow_up_mismatch`, `review_status_mismatch`, `not_enforced_condition_bound`, `quarantined_condition_bound`, `covered_action_not_executable`, `prerequisite_not_bound`, ...). Nothing silently continues with stale rules, so HeroOS never explains one version of the methodology while enforcing another.

## 6. One immutable snapshot per turn; built once

`ExecutionSnapshot` holds the knowledge bundle, the profile and per-workflow `WorkflowExecution`s with immutable indexes (Conditions, options, fact schemas, bound rules per jurisdiction, option ↔ Condition links, coverage). It is built at startup (`app.main.load_evaluation`), never per turn. `ExecutionRuntime.current()` is read **once** at the start of a founder turn. The catalog, retrieval, evaluation, phrasing view, grounding labels and continuation binding all use that snapshot, so a turn never mixes two versions even if a new snapshot is installed meanwhile (`tests/evaluation/test_golden.py::test_a_turn_never_mixes_two_versions`).

Each turn evaluates narrowly: the Conditions of the topics raised and of the decisions asked about, in the resolved jurisdiction. Cost grows with the matter, not with the library.

## 7. The workflow-neutral contract

```python
ConversationEvaluationService(runtime).evaluate(snapshot, EvaluationRequest(
    matter, workflow, company_jurisdiction, jurisdiction_conflict, clarification,
    facts, requested, topics, two_state, reconfirm, multiple_matters, pathway_candidate, declined,
)) -> ConversationEvaluation
```

`ConversationEvaluation` (schema `heroos.conversation-evaluation/1`): availability, matter, workflow, jurisdiction and its state, pathway candidate and ownership, the trusted fact state, Condition evaluations, action evaluations, review requirements, missing requirements, cautions, two-state states, the presentation, the safe-next-step intent and provenance (snapshot, knowledge digest, profile, definition, rule bundle). `record()` gives canonical plain data. These are plain frozen dataclasses: no FastAPI, Pydantic or browser concerns (`app/evaluation/model.py`).

The evaluator is pure: no I/O, no clock, no randomness; the same inputs give a byte-identical `record()`. It contains no workflow name (a test greps for that).

**Workflow registry.** `WorkflowExecutionRegistry` maps executor names to implementations (`intake`, `rule_bundle`). Every workflow uses the generic evaluator; a new workflow arrives as content (knowledge, a definition, a rule bundle with conversation rules and a profile), not as code. A workflow whose execution semantics genuinely differ may register its own executor; none does.

**The jurisdiction gate.** The Blueprint's operator-confirmed jurisdiction, while guidance is allowed, made less certain (never more) by the conversation: the AI noticing a different employer (`conversation_conflict`, tightening only) or the founder's trusted answer to HeroOS's own question about this employee (`case_different` escalates, `case_not_sure` blocks, `confirmed` resolves a conflict). While unresolved, no jurisdiction-specific step gets a jurisdiction-specific result, and no jurisdiction-specific Condition runs; shared guidance continues. "We're in Dubai" decides nothing.

## 8. Facts: three trust levels

| Level | What | Used for |
| --- | --- | --- |
| PROPOSED | The AI's reading only: inferred, approximate, low confidence, hedged, or contradicted by the founder's own words ("I did NOT speak to him" read as "yes") | Asking to confirm |
| ESTABLISHED_CONVERSATIONAL | The founder clearly said it (their words exist, M2-NEW-05) | The conversation: never asked again; never a rule's input |
| ENGINE_TRUSTED | A canonical, server-typed value the server itself derived | The only input any rule reads |

ENGINE_TRUSTED comes from exactly three places: a **direct answer** to the one question HeroOS asked last turn, parsed deterministically against that fact's schema; a **confirmation** of the server's own canonical reading of what the founder said ("Just to confirm: proposed suspension days: 20?" then "Yes"); or the **Company Blueprint**. HeroOS's own words are never evidence (the understanding phase never sees them; history assistant turns are never parsed). A different value stated explicitly now voids a trusted one until confirmed again (stricter, never looser).

**Canonicalization** (`app/evaluation/facts.py`) uses server-known schemas only: the definition's question kinds and options (a definition question keeps its own options: they are never duplicated), or the rule bundle's typed conversation facts (`yes_no`, `count` with a maximum, `choice`). Plain answers only: "Yes." → `yes`; "Eight." → `8`; "No, outside work" → the option whose label starts "No"; "Not sure" → `not_sure`. "I sort of spoke to him", "basically all week", "about 8", "Yes, but only verbally" → nothing (HeroOS asks). Sensitive facts are never typed, collected or trusted.

**Not over-confirming.** Confirmation is asked only for what a requested step's deterministic decision needs. A fact the founder already said is otherwise reused as said.

## 9. Conditions, actions and outcomes

**Condition evaluation** (`ConditionEvaluation`): category, status (`fired`, `not_fired`, `unknown`, `unavailable`, `not_evaluated`), the configured and the current action, follow-up state, missing facts, provisional. Three-valued logic: unknown never becomes false. An escalating rule whose inputs are unknown holds for missing information (block) instead of recording an escalation.

**Action evaluation** (`ActionEvaluation`), per requested step, by **stable option id** (never its title): the approved availability (`review_required` → escalate; `not_available` → block; a quarantined option → review), the jurisdiction gate, its mandatory-prerequisite rules, each linked Condition (executable: its result; question-only or quarantined: `unknown`; privacy-unavailable: `unknown`; guard-only and not-enforced: nothing more), and its coverage (not covered → `unknown`). Disposition by fixed precedence **ESCALATE > BLOCK > UNKNOWN > WARN > ALLOW**.

`allow` is never "lawful": only that no active deterministic HeroOS rule prevents the step on the trusted inputs and the compatible approved content. `unknown` is never clear: it is shown as a Warning ("HeroOS can't yet confirm that ... is clear of the approved safeguards").

A Condition can warn while the requested step is blocked by a missing prerequisite (a suspension over the cap, before the employee has been heard): both stay represented. A step held for review never puts the whole conversation into Expert Review: investigation guidance continues beside it.

**Requested actions** come from the understanding's new optional `requested_actions` (catalog option ids with the founder's own words, evidence-checked like facts). Recognizing a step only adds checks; not recognizing one never proves a safeguard doesn't apply (and reply safety still forbids authorizing anything). A direct answer keeps the previous turn's steps under evaluation (they travel in the continuation).

**Two-state Conditions** (warn first; stronger once the employer explicitly insists): the generic state is per bound rule (`TwoState`: shown, acknowledged, insists). After the caution is shown, HeroOS asks its own question ("Knowing this caution, do you still intend to go ahead with ...?"). Only a plain yes (or an explicit "I still want to go ahead") is insistence; "OK, understood" only acknowledges; tone, capitals and repetition are nothing. Acknowledging a caution is never an employment decision. A `condition_specific` follow-up runs its own predicate.

**Presentation.** Over the requested steps and the matter's own cautions: escalate → Expert Review, block → Block, unknown or warn → Warning, allow → Guidance. Ordinary missing context with nothing requested is Guidance and one question, never a Block. A Condition guarding a decision nobody asked for is a caution, never a hold on the conversation.

**ReviewRequirement**: `required`, scope (`action` with its option id, or `matter`), reason codes, and `service_available` (false: M2-NEW-09 doesn't exist). The card says "Specialist review is required before ..." and never mentions a ticket, an expert, a submission, an SLA or a response.

**Matters.** Another HR matter the approved content doesn't cover (`unsupported_hr`: probation, recruitment, workforce strategy...) is a matter-level specialist requirement shown as Expert Review. A request outside HeroOS (`outside_product_scope`) gets a neutral limitation and no outcome. Several matters are taken one at a time (`choose_matter`), never mixed into one evaluation.

**Pathway ownership.** The AI's pathway candidate guides retrieval and questions only. It never becomes employer-owned state, no conversation rule can read it, and the founder never picks HR taxonomy (the profile records the workflow's ownership mode: Disciplinary `employer_confirmation_required`).

**Business vs technical.** Business disposition: allow, warn, unknown, block, escalate. Technical availability: `ready`, `knowledge_bundle_missing`, `rule_bundle_missing`, `execution_profile_missing`, `incompatible_versions`, `unsupported_executor`, `privacy_capability_unavailable` (per safeguard), `invalid_continuation`, `internal_failure`. A technical state is shown as "Checks unavailable", never as a Block or Expert Review.

## 10. Phase B: the model phrases, never decides

The response phase receives `heroos_outcome`: the state, its meaning, the server's message, each step's result in words, the approved cautions (with "legal basis not confirmed: a practical caution, never the law" where the citation needs review), what is still needed, the safe next step and the rule that it can't be changed. The server's question target for a deterministic requirement carries the server's own wording; if the model doesn't ask it, the server appends it.

Every reply passes grounding (M2-NEW-05), reply safety (M2-NEW-05) and the **contradiction check** (`presentation.outcome_contradiction`): "you can go ahead (and dismiss)" under a held step, "no specialist review is needed" under Expert Review, "nothing to address" under a Warning. A failing reply is replaced by the server's fixed text and the deterministic result. Under a Warning, Block or Expert Review the safe next step is the server's fixed wording for the intent (never a sanction).

**AI failure never weakens safety.** If the provider times out, is rate-limited, fails, or returns invalid output after a Warning, Block or Expert Review was decided, the turn still answers with that outcome in the server's own words (and says it couldn't write a fuller reply). Ordinary Guidance that needs explanation still fails safely (no invented content).

## 11. The evaluation continuation (`heroos.evaluation-continuation/1`)

Trusted state crosses turns in one opaque token the browser sends back unchanged: AES-256-GCM under a key derived (HKDF-SHA256) from `HEROOS_EVALUATION_CONTINUATION_KEY`, a shared secret, so any API instance reads what another issued (no process-local state). It carries only canonical, non-sensitive state: what HeroOS asked (with a confirmation's canonical candidate), ENGINE_TRUSTED values, the trusted jurisdiction answer, two-state states, the previous turn's step ids, whether state was lost; plus its expiry (4 hours), keyed digests of the Company and the user, the identity of the knowledge and profile it was issued under, and a digest of the founder message it answered. Never a message, name, narrative, evidence, sensitive answer, provider output, knowledge text or guidance; the reader validates every value against the current schemas and refuses the token otherwise.

A missing, malformed, unknown-version, tampered, expired, other-Company, other-user, other-version, replayed (not the conversation it answered) or invalid token is **rejected** (a category for the log). Rejection only loses state, and lost state mid-conversation is **re-confirmed**: facts become unknown (stricter), and a two-state caution that fires holds its stronger action until the founder answers again. It never makes an evaluation less restrictive than the facts that remain. Bounded: at most 2,400 characters; facts are dropped first when it would overflow (stricter); two-state answers are kept.

Without a configured key, a per-process key carries only what HeroOS asked: never trusted state. A profile can't be installed without the key.

## 12. Browser contract and UI

`POST /companies/{id}/assistant/messages` now answers `{reply, safe_next_step, conversation_state, outcome, continuation}`, where `outcome` is `null` or `{kind: guidance | warning | block | expert_review | unavailable, title, message, items: [{kind, text}]}` (one line per requested step, at most four). Nothing else reaches the browser: no rule key, Condition id, binding, profile, trace, digest or snapshot id. The request still accepts only `{message, history, continuation}`: a browser can't send or change an outcome, a fact or a Condition result (422). The BFF rebuilds both field by field.

The Ask conversation shows the outcome with JJ's approved tones (`response-tone.tsx`): words and an icon, never colour alone; a Block shows its stop sign with the step ("Not yet: ..."); Expert Review is a requirement. The composer stays free in every state: a Block holds one step, never the conversation. "Checks unavailable" is a neutral note. No suggestion chips; free text stays primary.

## 13. Observability

The gateway's one log line per turn adds bounded fields only: workflow, evaluation availability, presentation, disposition counts (`a0w1u0b1e0`), ENGINE_TRUSTED count, conversational-not-trusted count, profile id and version, rule bundle version, continuation rejection category, evaluation latency (µs) and how the reply was worded (`model`, `fallback_safety`, `fallback_grounding`, `fallback_invalid`, `provider_<kind>`). Never founder text, employee data, fact values, sensitive answers, knowledge or Condition text. Startup logs the snapshot identity and, per unavailable workflow, its fixed code. There is no metrics backend; were one added, its labels must stay bounded categories (no digests, rule or Condition ids, Company or user ids, fact keys).

## 14. Activation (none done)

Beyond the M2-NEW-05 gateway prerequisites ([ai-gateway.md §13](ai-gateway.md#13-configuration-and-activation)), deterministic checks need:

- an approved execution profile, reviewed by HeroOS's technical authority (§14.1);
- the rule bundle it pairs, if any;
- `HEROOS_EXECUTION_PROFILE_PATH` and `HEROOS_EXECUTION_PROFILE_SHA256`;
- `HEROOS_EVALUATION_CONTINUATION_KEY`: a secret, the same value on every instance.

The rest of the contract stays as it is. The profile is private and SHA-256 pinned. It must match the installed knowledge, definitions, rule bundle and executors exactly (§5), and there is no silent fallback. Production refuses a synthetic or development profile. Until a profile is installed, the gateway works as in M2-NEW-05 and each turn's card says the checks are unavailable.

### 14.1 Who approves what

The profile's `approval` field is generic (`development` or `approved`); it names no person, and it shouldn't.

> **Technical approval is sufficient for faithful implementation of already-approved, unambiguous HeroOS rules. Technical approval is not authority to create, reinterpret, or resolve missing HR/legal methodology.**

| Authority | Approves |
| --- | --- |
| **Technical authority** (the Technical Lead, to whom JJ has delegated technical implementation and architecture decisions) | Execution-profile compatibility. The exact Condition → executor/rule bindings. The technical representation of a rule the approved HeroOS sources already establish unambiguously. Rule-bundle, schema and version compatibility. Provider and model configuration as architecture, after the evaluation in §14.2. Deployment and configuration mechanics |
| **Product / HR-domain authority** (JJ: HeroOS's methodology and approved content) | Anything the approved sources don't establish. That includes a new threshold, a choice between contradictory source rules, a change to the disciplinary methodology, a sanction, or a new business or product policy |
| **Legal / privacy authority** | What UAE Federal or DIFC law means where the approved material leaves it unresolved, whether an action is legally permissible, and the acceptability of data processing (the privacy decisions in `docs/privacy/decision-register.md`) |

Until the right authority resolves such a source question, the affected Condition stays non-executable. Engineering never resolves an ambiguous Condition by preference, and never turns Condition prose into a rule.

### 14.2 Production model and provider validation

Deterministic outcomes don't depend on the model (§9, §10). The conversation around them does. A model, provider, version, revision or inference configuration can behave differently in workflow and topic recognition, requested-action detection, structured extraction and canonical value proposals, ambiguity handling, clarification quality, structured-output reliability, grounding, wording and latency.

> **Synthetic/scripted-provider tests prove deterministic safety and integration behavior. They do not prove the conversational quality of a live production model.**

| Layer | What it proves | Where it runs |
| --- | --- | --- |
| 1. Deterministic engine tests | The same snapshot, ENGINE_TRUSTED facts and requested actions always give the same outcome | CI (`tests/evaluation/`) |
| 2. Scripted-model integration tests | Provider failures, malformed output and contradicting replies can't weaken a Warning, Block or Expert Review | CI, scripted provider only. Automated tests can't call an external provider (`app/assistant/live.py`) |
| 3. Exact production-model evaluation | Interpretation, extraction, clarification and phrasing quality for one specific provider, model, version and configuration | A controlled evaluation run before activation, never in normal CI |

**Before an external production model is activated**, its exact inference configuration goes through a HeroOS conversational regression evaluation (layer 3). The run:

- compares structured-output validity, interpretation and extraction behavior on representative and ambiguous cases, and grounding and reply-safety failure rates;
- checks latency and, where relevant, cost;
- confirms deterministic outcomes are unchanged for identical trusted facts.

**A model change is a controlled change.** A new version of the same model, another model of the same family, or another provider is never assumed to behave the same, and is evaluated again before it serves founders.

**Runtime identity.** The evaluated configuration is identified by:

- the provider and model identifier (logged at startup and on every turn);
- the model version or revision the provider reports, where it reports one;
- the prompt version, which is the deployed API commit (the instructions are code: `app/assistant/gateway/prompts.py`);
- the knowledge runtime digest (logged per turn);
- the execution profile id, version and digest (logged per turn and at startup);
- the gateway settings (`HEROOS_AI_GATEWAY_*`).

The evaluation record cites these. Nothing about it logs founder text, prompts, replies, facts or other sensitive data, and it adds no high-cardinality telemetry.

## 15. The M2-NEW-07 handoff

`Handoff.evaluation` carries the `ConversationEvaluation` (server-side only; never sent to the browser or stored). Its `record()` is the versioned contract M2-NEW-07 can persist: trusted facts and their sources, workflow, jurisdiction, compatible execution identity, action evaluations, review requirements, provenance. M2-NEW-07 must never trust an evaluation a browser returns: the server re-validates and re-evaluates before persisting.

## 16. Known limitations and future scale (documented, not built)

- Real coverage today: only the Conditions the M2-NEW-04 runtime already links to intake rules are executable. The private audit of the current runtime counts 42 Conditions: 4 executable (one of them reads only sensitive inputs, so a conversation can't collect them), 10 guard-only, 24 question-only, 4 not enforced and 0 quarantined. A supported real step is therefore shown as "not confirmed yet" (Warning), never as clear.

  This isn't an architecture defect: the evaluator refuses to invent executable logic. More coverage needs explicit rules and bindings. The Technical Lead may approve a faithful technical translation of already-approved, unambiguous HeroOS content (§14.1). A rule that is missing, ambiguous, conflicting, legally unresolved or would create new HR methodology stays non-executable until the appropriate product, domain or legal authority resolves the source rule.
- `OPTION_KINDS` (M2-NEW-04) is a closed Disciplinary vocabulary; other workflows reuse its kinds until the runtime grows its own.
- Usage limits stay per process (M2-NEW-05); shared, distributed rate limiting is future work, like durable conversations, case facts, workflow progression, Expert Review and shared event history (M2-NEW-07/09). No Redis or queue was added.
- The checks are patterns over replies (contradiction, safety, grounding): defence in depth, not a legal classifier.

## 17. Tests

- `tests/evaluation/test_profile_snapshot.py`: profile schema and pin, every compatibility failure, bindings, coverage categories, immutable snapshots.
- `tests/evaluation/test_facts.py`: canonicalization and the trust pipeline (§107 cases).
- `tests/evaluation/test_continuation.py`: confidentiality, binding, tampering, expiry, replay, size, schema, multi-instance.
- `tests/evaluation/test_evaluator.py`: Condition/action separation, two-state, precedence, coverage, jurisdiction, review boundaries, suspensions, technical availability, determinism, no workflow branches, the synthetic second workflow.
- `tests/evaluation/test_golden.py`: golden conversations A–S through the gateway, AI failures, contradictions, snapshot consistency, multi-instance continuation, lost state.
- `tests/evaluation/test_presentation.py`, `tests/evaluation/test_configuration.py`.
- `tests/auth/test_gateway_evaluation_api.py`: the outcome through the real application, nothing internal, no writes.
- `tests/evaluation/test_real_runtime.py`: the real artifacts (local only: `KNOWLEDGE_BUNDLE=… EXECUTION_PROFILE=… uv run pytest tests/evaluation/test_real_runtime.py`).
- Fictional content: `tests/fixtures/evaluation.py` (a fictional cap, prerequisite rules, and the invented second workflow `synthetic_probation`).
- Web: `components/ask/ask-conversation.test.tsx`, `lib/server/gateway-bff.test.ts`.
