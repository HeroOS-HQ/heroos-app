# Disciplinary as the End-to-End Reference Workflow (M2-NEW-08)

**Status:** implemented on `feat/m2-new-08-disciplinary-reference-workflow`. **No migration** (schema contract stays **9**, D6 `8860b86ef2ba`). **No WorkflowDefinition change** (Disciplinary stays **v2**). Not deployed, nothing activated: the AI gateway stays off by default, no execution profile or private bundle is installed by this change (§12).

> AI controls the conversation. Approved HeroOS methodology controls the guidance. Deterministic workflow state, Conditions and jurisdiction controls remain authoritative. The employer makes the final employment decision.

M2-NEW-07 made Ask HeroOS conversations persistent and attached them to real Cases. M2-NEW-08 joins them into one workflow:

- Ask HeroOS reads the Case's real workflow position;
- an employer decision's prerequisites can need the Case's formal record;
- the Case is **chat-first**: its formal steps appear inline in the conversation;
- the Case page becomes the secondary review and record surface.

There is still one workflow authority: the M2-03 progression engine.

## 1. The journey

```text
Founder: "Hi Hannah"                → a greeting back; no model request, no Case
Founder describes the situation     → Ask HeroOS understands it; a supported Disciplinary Case is created
HeroOS asks one useful question     → the founder's direct answers become ENGINE_TRUSTED facts
                                      → saved through the shared Case mutation pipeline (CaseFacts)
Case steps appear inline in the chat → only by the founder's click, through the Case's own routes:
   the employee's jurisdiction, the safety screening (never collected by the AI)
   the pathway ("your decision")    → POST …/progression/pathway
   start / checklist / complete      → POST …/progression/transitions, PUT …/steps/{stage}/answers
   a caution: "I understand"         → the acknowledged warnings, exactly
Ask HeroOS reads the new position next turn (never from its own earlier words)
Founder: "I want to dismiss them without notice."
   → the M2-NEW-06 ActionEvaluation: jurisdiction, prerequisites (incl. the Case's record),
     Conditions, availability → Guidance / Warning / Block / Expert Review
   → nothing is recorded as dismissed, warned, suspended or deducted
Leave, reload, sign in again        → the same chat, Case, pathway, stage and attention
```

## 2. Ask HeroOS reads the Case's progression (read-only)

`app/conversations/progress.py` builds the Case's position from the Case's own records (`CaseState`: progress events, checklist answers, the intake), on every turn, twice:

1. when the turn starts;
2. again at commit, under the instance lock (§7).

It produces three things. None of them is ever written by the AI.

| Product | Used by | Contents |
| --- | --- | --- |
| `CaseProgress` (`app.evaluation.model`) | the deterministic evaluation | stages the employer completed and the stage checklist answers they saved, with the jurisdiction the Case's progression runs under |
| `case_progress` (the response phase's data) | the model | **labels only**: the case lifecycle, the workflow status, the recorded pathway (with "recorded by the employer… HeroOS didn't classify the conduct"), the stage in progress, stages completed and next, what the stage still needs, what the company can do now in the Case and what isn't possible yet (with the reasons' titles), steps held for specialist review, the employer's pathway choices in HeroOS's neutral public wording (before one is recorded), the decisions needing Expert Review (titled from the turn's own snapshot), and "who changes it" |
| `Position` (the status) | the browser | the progression status, the recorded pathway's label, the stage in progress or next, the steps held for specialist review |

The model never receives a stage key, a rule, a raw row, an answer value, the rule bundle or a provider trace. The fixed instructions say `case_progress` is read-only and authoritative:

- the model says what the employer recorded, and never that it or HeroOS chose a pathway, started or completed a stage or approved anything;
- if the founder says a stage is done and the Case doesn't show it, the model says the Case doesn't show it yet;
- for the pathway, a stage or a checklist, the model points the founder to the Case.

The reply checks (`app/assistant/response_safety.py`) back this up:

- `action_claim` now also catches "I/HeroOS started/completed/selected/approved …" about a formal step;
- a new `misconduct_finding` catches "this sounds like serious misconduct" and "misconduct has been proven".

Saying what the employer recorded stays allowed ("your company has recorded the serious pathway").

## 3. Who owns each formal step

| Step | Owner | How |
| --- | --- | --- |
| Pathway | the employer | an explicit click (inline in Ask HeroOS, or on the Case page) → the existing pathway route. The AI's `pathway_candidate` stays a candidate in the evaluation record (`pathway.ownership = employer_confirmation_required`), never a progress event |
| Start / complete a stage | the employer | the existing transitions route; the engine decides ALLOW / WARN / BLOCK / ESCALATE |
| Stage checklist | the employer | the existing answers route (stage step); the inline card asks one question at a time |
| Caution acknowledgment | the employer | "I understand", then the step; the acknowledged warnings are sent exactly as the API named them |
| The employee's jurisdiction; the safety screening | the employer | the existing answers route; the AI never collects them (M2-NEW-07 boundary kept) |
| Ordinary facts | the founder, in their own words | ENGINE_TRUSTED values (a direct answer or a confirmation) through the shared Case mutation pipeline (M2-NEW-07) |
| The employment decision | the employer | outside HeroOS. HeroOS evaluates a requested decision; it never records or issues one |

"Start the investigation" or "mark it complete" in the chat moves nothing. The model may explain where the step is; an action claim is replaced by fixed text. The inline cards (`apps/web/src/components/ask/case-steps.tsx`) and the Case page's Next steps call the same routes through one hook (`use-case-request.ts`).

## 4. Requested decisions: ActionEvaluation, never an employer decision

The M2-NEW-06 evaluator is reused unchanged in its semantics:

- precedence: ESCALATE > BLOCK > UNKNOWN > WARN > ALLOW;
- presentation: Guidance, Warning (WARN and UNKNOWN), Block, Expert Review;
- `allow` means only that no active deterministic HeroOS safeguard prevents the step on the trusted inputs and the compatible approved content;
- two-state cautions, three-valued logic, coverage and ReviewRequirement are as before.

M2-NEW-08 adds three things:

- **Prerequisites can read the Case's formal record.** An employer decision's prerequisite rule may now read `{"stage_completed": "<stage>"}` and a stage checklist answer (`progress.<stage>.<item>`). That covers the rule bundle's conversation `actions` only, never a Condition's rule, and only that jurisdiction's programme (validated at parse).
  - The evaluator gives them the Case's completed stages and checklist answers **only when the evaluation resolves the jurisdiction the Case's progression runs under**. Anywhere else no stage is completed and no checklist answer is known: never another jurisdiction's record.
  - The founder's words (even ENGINE_TRUSTED) never satisfy such a rule.
  - What is missing there is never asked in the chat. It produces the next step `complete_case_step` and the fixed note "This depends on your case's own record…".
- **Hypothetical versus intended.** The understanding schema gains an optional `hypothetical_actions`.
  - A decision the founder asks about only hypothetically ("What if I dismissed them?") is evaluated, so the answer is accurate, and marked `hypothetical`.
  - It never creates an active review, is never carried as still requested, and is never asked "do you still intend to go ahead?".
  - The founder's own words decide: a requested action whose excerpt is a "what if" is reclassified server-side, whatever the model read.
  - "I want to dismiss them" is an intention. An intention and a hypothetical about the same decision in one message: the intention wins.
- **Nothing is executed.** HeroOS records no dismissal, warning, suspension or deduction, and adds nothing to "Decisions & history", whose categories stay non-authorizing (M2-04). The concepts stay separate: factual employer record ≠ requested employment action ≠ workflow progression authorization ≠ HeroOS guidance.

**Serious misconduct.** A serious concern is not a finding, and a finding is not a dismissal:

- describing serious conduct requests no decision;
- the AI's pathway candidate is never persisted;
- the model may not classify the conduct;
- formal stages are still required before any decision's prerequisites can be met.

## 5. Expert Review: two mechanisms, kept apart

| | Old progression escalation (M2-03) | Action/matter ReviewRequirement (M2-NEW-06/07) |
| --- | --- | --- |
| What | a formal transition the progression rules escalated | a requested decision (or the matter) the evaluation found needs review |
| Lifetime | sticky per transition (no release exists) | current: ends on a fresh evaluation that no longer requires it, or an explicit withdrawal |
| Shown | Next steps ("Specialist review needed"), the case status ("Specialist review needed before: <step>"), the conversation position (`held_steps`) | the conversation status (`attention.expert_review`, scope `action`/`matter`, titles) and the turn's outcome card |
| Pauses the Case? | no: it holds that transition | an action review never does; only the intake's whole-matter specialist-review hold makes the lifecycle `paused` |

Since M2-NEW-08 the Case header no longer shows a transition escalation as the Case's status. The pill keeps the Case's own status; the escalation stays on its step.

**08/09 boundary.** HeroOS shows "Expert Review needed" as a requirement only:

- no request, ticket, submission, queue, consultant, HeroOS Expert identity, returned answer, quota or pricing;
- `service_available` stays `false`;
- the reply checks refuse "I've sent this to an expert" and "an expert will reply".

## 6. Case status and the chat-first Case page

The status keeps its separate dimensions, now with the workflow position:

```text
lifecycle      in_progress | paused (whole-matter hold only)
workflow       disciplinary
position       pathway (your decision), stage in progress / next, steps held for review   ← M2-NEW-08
attention      needs information, jurisdiction needs confirmation, Expert Review (action | matter)
checks         ready | unavailable | not_applicable
latest outcome guidance | warning | block | expert_review | unavailable | none
```

"Dismissal without notice → Expert Review" while the investigation goes on is `lifecycle: in_progress`, `attention.expert_review.scope: action`. It is never "Case status = Expert Review".

**Chat-first.** Ask HeroOS is the conversation, and the Case page is no second one. The Case page (`case-workspace.tsx`) now shows, in order:

1. **Continue with HeroOS** (or **Ask HeroOS** for a Case opened another way);
2. the Case notices: the hold, the cautions and the case jurisdiction, in the API's words, never folded away;
3. **Case details**, folded until "Review case details": the same structured answers form, the same route and validation;
4. Next steps (the same formal controls as the inline cards);
5. Decisions & history;
6. Documents.

The guided workflow's old chat thread isn't shown. Its historical welcome ("a guided workflow, not an AI assistant") stays with WorkflowDefinition v2 (§9). The API's record framing is now `app.workflows.conversation.CASE_RECORD`.

**Greetings.** A message that is only a greeting gets "Hi! What can HR help you with today? …". This holds on both paths:

- with the gateway (no model request, no Case, nothing evaluated);
- on the M2-NEW-02 case-opening seam used while the gateway is off. The browser answers locally, and the BFF refuses to open a case for a greeting (`422 greeting`), so "Hi Hannah" is never saved as "What happened?".

## 7. Concurrency (M2-NEW-07, unchanged and extended)

No row is locked during a model request. At commit the conversation service locks the instance and reloads three things:

- the Case's facts;
- **its position** (`case_context` again);
- the Blueprint.

It then re-runs only the deterministic evaluation. The reply's signature now includes the Case position, so:

- another administrator completing the required stage meanwhile relaxes a Block (`relaxed`). The fresh result wins and the stale model wording is replaced by the server's fixed text;
- a position the reply's words rested on that changed is refreshed;
- uncertainty never relaxes (trust lost, the jurisdiction no longer resolved, a fact lost or unknown); the stricter prepared reply is held.

## 8. Jurisdiction

UAE Federal and DIFC never blend:

- action rules and Conditions are per jurisdiction;
- Case progress applies only under its own jurisdiction;
- a stage or checklist of another programme can't even be referenced (parse error).

Unknown, changed or conflicting jurisdiction pauses **jurisdiction-dependent** guidance, not the Case. When the Blueprint changes, the Case's confirmation becomes outdated:

- the evaluation's jurisdiction is unresolved;
- `case_progress.applied = false`;
- every decision is held for the jurisdiction (`confirm_jurisdiction`);
- the lifecycle stays `in_progress`.

In the current public intake rules, a Case confirmed as DIFC gets a whole-matter specialist-review hold, because no approved DIFC screening exists. That independent hold is what pauses it, never a decision's review.

## 9. Decisions recorded here

- **WorkflowDefinition: unchanged (v2).** Only presentation framing was obsolete. The definition's own welcome text is versioned history; the Case record's current framing lives in the presentation layer (`CASE_RECORD`, `record_title`). No question, step, gate or validation changed, so no v3 and no compatibility change is needed.
- **Schema: no migration.** Everything is represented by existing records:
  - the evaluation record (`assistant_turn_evaluations.record`) gains additive optional fields: `actions[].hypothetical` and `case_progress` (`{jurisdiction, applied, completed, checklist_answers}`). Earlier records read as "intended" and "no Case progress";
  - the checkpoint is unchanged;
  - progress events, CaseFacts and the timeline are unchanged.
- **Rule bundle schema:** still `heroos.rule-bundle/1`. A prerequisite may now read stages and checklists (additive), and existing bundles parse unchanged with the same digest.
- **Understanding schema:** still `heroos.understanding/1`, with the additive optional `hypothetical_actions`.

## 10. HTTP and BFF additions

- `GET /companies/{id}/assistant/conversations/{id}` and the turn response: `status.position` (`{state, label, pathway, stage, stage_in_progress, held_steps}` or null). The web parser accepts its absence (an older API), so a web deploy may come first.
- `GET /bff/companies/{id}/cases/{caseId}/workflow` (new, read-only, same-origin and session guard) → the existing `GET …/cases/{caseId}/workflow`. It is the Case's view for the inline steps.
- `POST /bff/companies/{id}/ask` refuses a greeting (`422 greeting`) before creating anything.

## 11. Tests

- `tests/conversations/test_reference_workflow.py`: the brief's scenarios A–Q through the real app (Ask turns, the Case's routes, SQLite stand-ins).
  - A: greeting, Case creation, ordinary fact.
  - B/C: pathway ownership, serious misconduct.
  - D: progression context, no chat-driven transition.
  - E/L/O: a Case-step Block, its recovery, and another administrator's stage relaxing it at commit.
  - F: suspension duration, prerequisites and unknowns.
  - G/M/Q: deduction review, action scope, no ticket.
  - H: DIFC dismissal, no Federal leakage.
  - I: same-incident sanction.
  - J/K: hypothetical vs explicit.
  - N: reopen and a new sign-in.
  - P: jurisdiction change.
- `tests/evaluation/test_case_progress.py`: jurisdiction isolation of Case progress, words never satisfying a Case step, hypothetical evaluation.
- `tests/workflows/test_conversation_rules.py`: prerequisite stage and checklist validation.
- `tests/assistant/test_reference_workflow_gateway.py`: greetings, hypothetical words, the new reply checks, the instructions.
- Web:
  - `components/ask/case-steps.test.tsx`: next-step selection, the inline pathway, checklist, caution and jurisdiction cards through the existing routes, the greeting seam, and the status position parser;
  - the Case page tests: chat-first layout, details folded, no guided thread, the pill keeps the Case's status.
- E2E: the existing suites updated for the chat-first Case page. The browser can't drive Ask HeroOS turns in CI, because test runs never reach a provider (M2-NEW-05 `live.py`). The golden journey is proven through the real HTTP routes (above).

## 12. Activation needs (private, not in this repository)

Before staging shows these behaviours, the private runtime needs:

1. **A private rule bundle with a conversation section.** The installed JJ draft bundle has progression stages but no conversation rules. It needs:
   - the facts the conversation rules read;
   - the Conditions' rules;
   - each covered decision's prerequisites, optionally stage-backed (`stage_completed`, `progress.<stage>.<item>`) for the investigation and employee-response prerequisites.

   It must be JJ-approved, then installed with its pin.
2. **An execution profile pairing it.** The private dev profile has no rule bundle and no covered actions, so every requested decision is `unknown` (Warning) today. The profile must pin:
   - the knowledge digest;
   - the definition v2;
   - the bundle id, version and digest;
   - the executors;
   - the bindings;
   - the covered actions with their prerequisite rules.
3. **The gateway enabled** (M2-NEW-05 activation gate) and the API deployed with this code. No migration is needed (contract 9).
4. **The synthetic demo screening.** Progression opens only once the intake is recorded with a cleared screening; with `HEROOS_SENSITIVE_SCREENING=disabled` (the default) the stages stay gated (M2-02/03 behaviour).

## 13. Known limitations

- Ordinary free-text intake details ("What happened?", dates) reach the Case from the chat only when the approved runtime maps them as canonical facts. Otherwise the Case asks the founder to tell HeroOS or review them in the case details: free text is never copied from the chat into a Case fact.
- The inline Case steps show the current next step, not a replay of earlier formal steps in the thread; those are in the Case's history.
- Progress events don't store the jurisdiction they were recorded under. Case progress is limited to stages of the current jurisdiction's programme, and applies only when the evaluation resolves that same jurisdiction.
- Retention, deletion and PRIV-020 stay open (M2-NEW-07).
