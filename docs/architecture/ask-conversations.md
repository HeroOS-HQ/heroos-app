# Ask HeroOS Conversations (M2-NEW-07)

**Status:** complete (Parts 1 to 3): persistence, the persistent API and BFF contract, and the Ask HeroOS history UX. Migration D6 (`8860b86ef2ba`), schema contract 9. Not deployed, D6 not applied to staging, nothing activated (the gateway stays off by default, M2-NEW-05).

> **Current architecture (M2-NEW-08):** Ask HeroOS reads the Case's workflow position, the Case is chat-first (its formal steps appear inline in the conversation) and requested decisions can need the Case's formal record. See [disciplinary-reference-workflow.md](disciplinary-reference-workflow.md). This document stays the record of what its own milestone built.

> AI controls the conversation. Approved HeroOS methodology controls the guidance. The employer makes the final employment decision.

HeroOS persists the **user-visible** conversation so authorized users can reopen and review it: the founder's messages, HeroOS's visible replies (with the safe next step and the outcome card), timestamps and authors, the Case it belongs to, and the minimum durable state a correct resume needs. It never persists provider requests or responses, hidden or system prompts, reasoning, provider scratch state or duplicate payloads. Retention duration, deletion mechanics and PRIV-020 stay open (§12).

## 1. The model

```text
CASE
├── Conversation (Ask HeroOS chat, at most one per Case)        ← reopened from History or the Case
│   ├── Turn 1 ─ Message (founder) ─ Message (HeroOS) ─ ConversationEvaluation (server-only)
│   └── Turn 2 ─ …
└── Case record
    ├── WorkflowInstance ─ WorkflowSubmission (structured | assistant) ─ CaseFact
    ├── WorkflowEvaluation (intake), progress events, decision records
    └── Case timeline / "Decisions & history"
```

- **Conversation** (`assistant_conversations`): belongs to the Company, at most one Case (set once), a revision (one per completed turn), a server-chosen title, the checkpoint.
- **Turn** (`assistant_turns`): one completed exchange, with its `turn_key` (the idempotency key) and its sequence. A turn is all-or-nothing: no founder message is ever stored without HeroOS's reply.
- **Message** (`assistant_messages`): exactly two per turn, the founder's (`actor_user_id`) and HeroOS's (no actor; the visible reply, safe next step, conversation state, outcome card).
- **ConversationEvaluation** (`assistant_turn_evaluations`): the M2-NEW-06 deterministic record of that turn (and the decisions the founder withdrew in it). It is **not** the Case's `WorkflowEvaluation`: the intake evaluation stays the structured workflow's own and is appended only when the Case's facts change (§6).
- **Chat history and the Case timeline stay apart.** The chat is never copied into the Case record; the Case's guided conversation and history say only "Case information updated through Ask HeroOS" (labels, never values) when a conversation changes a Case fact.

| Module | Role |
| --- | --- |
| `app/db/models/assistant.py` | The four tables (vocabularies and storage bounds) |
| `app/repositories/assistant_conversations.py` | Company-scoped persistence and keyset reads (flush, never commit) |
| `app/cases/mutation.py` | The shared Case mutation pipeline (the form and Ask HeroOS) |
| `app/conversations/service.py` | One persisted turn (replay, load, answer, reconcile, record) and the reads |
| `app/conversations/checkpoint.py` | The next turn's trusted start, active reviews, how both are rebuilt |
| `app/conversations/bridge.py` | The Case threshold, the safe title, which facts may enter a Case |
| `app/conversations/status.py` | The status projection (separate dimensions) |
| `app/assistant/gateway/service.py` | `reconcile`, `uncertainty`, the employee-jurisdiction knowledge narrowing |
| `app/api/gateway.py` | The HTTP contract |
| `apps/web/src/lib/ask/conversation.ts`, `lib/server/bff.ts` | Field-by-field shapes; the BFF routes |
| `apps/web/src/components/ask/*`, `components/cases/case-conversation-link.tsx` | The Ask page, History, the Case's link to its chat |

`app/assistant` still can't reach the database or the workflow engine, and the route reaches persistence only through `app.conversations` (import-boundary tests).

## 2. The HTTP contract

| Route | |
| --- | --- |
| `POST /companies/{id}/assistant/messages` | One turn. Request `{conversation_id?, expected_revision, turn_key, message}`, nothing else (`extra="forbid"`): no history, facts, workflow, pathway, jurisdiction, Case, status, outcome, evaluation, profile, digest, checkpoint or continuation. Response `{conversation, messages[2], replayed}` |
| `GET /companies/{id}/assistant/conversations?limit&before` | The Company's conversations, most recently active first: `{items[{id, title, case, created_at, updated_at}], next_before}` |
| `GET /companies/{id}/assistant/conversations?case_id` | The conversation a Case is attached to (zero or one item; never combined with `before`) |
| `GET .../conversations/{conversation_id}?limit` | `{conversation, messages, next_before}`: summary, revision, current status, latest messages |
| `GET .../conversations/{conversation_id}/messages?before&limit` | Older messages: `{messages, next_before}` |

- **Who.** Every route needs an active `company_admin` of the Company in the path. The message POST is an administrator write: the role is checked again inside the transaction, and again after the provider answers. The reads use a transaction that refuses writes. Another Company's conversation is indistinguishable from none (404). A member gets 403. The conversation belongs to the Company: any of its administrators reads and continues it.
- **Authors** are relative to the viewer: `you`, `another_administrator` or `heroos`, never an id, email or identity.
- **Never returned:** Condition ids, rule ids, raw fact keys, the evaluation record, snapshot, profile or rule-bundle digests, the checkpoint, or provider fields. Decisions are shown by title only.
- **Errors:** 404 (unknown conversation, or the gateway disabled for a new turn), 409 (a conflict, §4), 422 (field locations only, never the value), and 429, 502, 503 and 504 as M2-NEW-05. A failed turn stores nothing. Stored conversations stay readable while the gateway is off.

**BFF.** `/bff/companies/{id}/assistant/messages` (POST, shared CSRF and session guard, bounded body) and three GET reads (same origin, a valid session, only the named query parameters: `before`, `caseId`). Each rebuilds the request and the response field by field: the browser's `{message, turnKey, conversationId, expectedRevision}`, and only the approved fields back.

## 3. One turn

1. **Check** the message against the stored rules (non-blank, at most 2,000 characters, no control character other than tab, line feed and carriage return).
2. **Replay.** If the Company already has a turn with this `turn_key`, it is returned (`replayed`) with no provider request. Another message, administrator, conversation or revision with the same key is 409.
3. **Load** (a short read): the conversation (409 here, before any model request, if its revision isn't the expected one), its latest 12 visible messages, its checkpoint, its Case's facts, their revisions and the Case's jurisdiction status, and the Company Blueprint. **The transaction ends before the provider is called.**
4. **Answer:** the gateway runs with `FounderTurn.resume`. The context is the current Blueprint, the Case's current facts, the validated checkpoint, the bounded recent messages and the current approved runtime. It survives reloads, sign-outs, restarts, other API instances, expired M2-NEW-06 continuations and other administrators. The old encrypted continuation is not read and not returned.
5. **Record** (a short write):
   - re-check the role;
   - lock the conversation (a first turn creates it) and refuse a consumed revision (409);
   - lock the Case's `WorkflowInstance` like every writer of it;
   - reload the Case's facts and the Blueprint;
   - **reconcile** (§4);
   - append the turn, the two messages and the evaluation record;
   - create the Case at the threshold;
   - apply the founder's new canonical facts through the shared pipeline;
   - write the active reviews and the next checkpoint, and bump the revision.

   A unique violation (the same turn key committed meanwhile) rolls back and replays.

No row is locked during model latency: a PostgreSQL test checks `pg_stat_activity` and `pg_locks` at every model request, for a first turn and for a turn on a conversation with a Case.

## 4. Concurrency

- **Conversation revision.** Two different turns sent at the same expected revision: one commits, the other is 409 (refused before any model request if it is already stale). Merging is unsafe: what HeroOS asked last, which a direct answer refers to, has moved on.
- **First-turn idempotency.** The same request sent three times at once through the API gives one conversation, one turn, two messages, one Case and one evaluation; the other requests replay with no model request. A first turn whose response was lost, sent again, replays. Tested on PostgreSQL.
- **Commit-time reconciliation** (`AiGateway.reconcile`). The model's reply was prepared on the Case as it was. At commit, the deterministic evaluation runs again on the current Case and Blueprint, with the same snapshot and the same understanding, and **no model request**. The response persisted for a completed turn corresponds to the **freshest authoritative state** in the commit transaction:

  | At commit | Stored |
  | --- | --- |
  | the same result | the model's wording (`kept`) |
  | a result at least as strict | the M2-NEW-06 fixed server text for the current result ("This case changed while I was answering, so here is HeroOS's current result." plus the current card and question) (`refreshed`) |
  | a weaker result on **authoritative** state | the same fixed text for the current result; the stale stricter wording is discarded (`relaxed`) |
  | a weaker result only because something became **less certain** | the stricter reply that was prepared (`held`) |

- **Authoritative relaxation vs lost-state safety** (`service.uncertainty`). A weaker result is authoritative only when nothing it rests on became less certain: the checks are ready; no trusted state was lost (no new re-confirmation); a resolved jurisdiction is still the same resolved one; every ENGINE_TRUSTED fact is still trusted and not "Not sure"; no safeguard that applied became unknown, unavailable or unevaluated. Example: a written warning is blocked because the expected standard wasn't explained; another administrator records that it was; the fresh result is Guidance and Guidance is stored. Counter-examples, all `held`: the answer turns into "Not sure" (a Warning would otherwise become Guidance); the Case's jurisdiction is answered "Not sure" while a dismissal awaits Expert Review (it would otherwise only be blocked for the jurisdiction); the Company jurisdiction changes. Uncertainty never weakens a Warning, Block or Expert Review. A held reply still stores the **current** next state: what was lost stays lost and is re-confirmed on the next turn, never carried into the new checkpoint binding.

  A harmless concurrent change commits normally. 409 is only for a consumed revision, a reused key or a changed Case or workflow association.

## 5. Conversation or Case

A Case is created only when the evaluation says the matter is a supported HR matter of an established workflow from the approved catalog that has a real `WorkflowDefinition`. It must also be one matter (`multiple_matters` from the evaluation, or from the understanding when the checks couldn't run), the conversation must have no Case yet, and it must have established no other workflow. It is created through `create_workflow_case` with `request_key = uuid5(namespace, conversation id)` (idempotent). A conversation has at most one Case, and a Case at most one conversation. Nothing is chosen in the UI: no workflow, Case type, pathway, stage or title.

- **Title.** The server's, never a name. It is a neutral matter label from a closed map of approved topic keys (`bridge.TOPIC_TITLES`; today `misconduct_level` → "Conduct concern"), otherwise "Disciplinary case · 22 Oct". Never a sanction, an employer decision, the AI's pathway or its summary. Richer labels are a later content refinement.
- **CaseSubject.** Never created or linked from a name in free text.
- **Unclear, then clarified.** An unclear first message is stored without a Case; once a supported matter is established, one Case attaches to the same conversation.
- **Unsupported HR.** Kept as a conversation without a Case. Its matter-level review requirement is persisted with it (the evaluation record and the active reviews). Outside HeroOS (for example, programming help): stored, no Case.
- **Separate matters.** A separate incident in a Case's conversation writes nothing into that Case and carries nothing it established. HeroOS asks which matter to take (`choose_matter`). There is no automatic multi-Case creation.

## 6. Facts: one mutation pipeline

`apply_case_fact_changes` is the only way a Case's facts change. It runs under the instance lock, on state read under that lock:

1. compare-and-set the revision;
2. append the submission with its origin, and its facts (append-only: the latest wins, an unchanged value is refused);
3. append the intake `WorkflowEvaluation`;
4. record newly escalated transitions.

The form (`FormOrigin`) and Ask HeroOS (`AssistantOrigin(founder message id)`) differ only in input validation, so an assistant-origin fact has every side effect of a form save.

A conversational fact is checked as a **value**, never by the founder's path through the form (`bridge.fact_changes`):

- it must be ENGINE_TRUSTED (a direct answer, a confirmation, or an earlier turn's trusted fact carried before the Case existed);
- of a non-sensitive question of the Case definition's own steps. A stage checklist is never written from a conversation: it belongs to a stage the employer starts;
- its step's **semantic workflow gate** (`StepGate`: Company jurisdiction confirmed, screening covered) must be open. An ungated step is always open: nobody has to have opened it in the form;
- it must pass the form's validator (`validate_answers`: an option, and `AskWhen`: a follow-up only once its premise is known). A trusted value that can't be saved yet waits in the checkpoint and is saved by the turn that makes it valid.

Never a PROPOSED or conversational reading, a Blueprint value, the Case's own value carried into the turn, a requested action or a hidden summary. **Employer-owned actions are never inferred:** conversation never creates `pathway_selected`, `stage_started`, `stage_completed`, a decision record, a sanction, a dismissal, an investigation's completion, a document or a letter, and never confirms the Case's jurisdiction. Those stay the employer's own requests (AI understands; the employer acts).

**Provenance.** An assistant submission has `origin = 'assistant'`, `step_key = 'ask_heroos'` and its founder message's id (a Company-qualified reference). **Corrections** append: the old Case fact stays, the new one is appended, the latest wins.

**Founder corrections (refined in the correction reliability pass, Technical Lead decision 2026-10-24).** The original rule still holds: the model's output never changes the Case by itself. It is refined for one case. A **validated explicit founder correction** of a Case fact **the conversation wrote** (`origin = 'assistant'`) is superseded by the server's deterministic correction processor (`bridge.correction_changes`).

How a correction is validated:

1. The understanding names what the current message corrects (`corrections`, apart from the new value).
2. The server checks it against the founder's own words in the current message, never a bare yes, no or "not sure".
3. The fact must have held a value in the conversation.
4. The correction must be said plainly (ESTABLISHED_CONVERSATIONAL), answered or confirmed, or be a validated take-back (`withdrawn_facts`). A hedged or uncertain contradiction doesn't qualify.

What a supersession writes:

- The Case's answer becomes the corrected value when that value is trusted (a direct answer or a confirmation saves itself through `fact_changes`).
- Otherwise it is cleared: an appended `CaseFact` with no value. The founder's new words are noted for the employer to save.
- The earlier value stays in the record as superseded, with the message it came from and the correcting message (`history.fact_versions`). The Case history reads "Case information corrected through Ask HeroOS", with labels only.

What it never touches:

- What the employer saved in a step's form.
- The narrative.
- What records a formal act of the employer's (`EMPLOYER_OWNED`: an earlier action put in writing, a sanction already applied).
- Facts the correction didn't name.

Pathway, stages, decisions, sanctions, suspensions, deductions and dismissals are never Case facts here at all.

The rest keeps the earlier behaviour. A reading the founder's words don't support changes nothing. A hedged contradiction, or one of an employer-owned value, changes nothing in the Case. It voids the Case fact in the conversation until a value is confirmed or the Case records a newer one.

Why the rule was refined: in the blocker pass, "Nobody actually saw it" left the Case's "witnesses: yes" in place. That value had been saved from the conversation. The conversation itself no longer relied on it, so the Case record said what the founder had just withdrawn.

**Unresolved corrections.** Some corrections name a fact but leave nothing usable in its place, for example when the new value isn't read. The earlier value is then no longer relied on: it isn't trusted, said or noted, and the Case's value is voided in the conversation. Nothing is guessed, and the Case isn't changed. HeroOS asks one focused question in its own words: "Just so I get your correction right: …". The founder's answer is read like any other answer. A plain one is a direct answer, trusted and saved through the normal path.

**People mixed up with the employee.** The understanding gives the employee's name as the founder writes it, and the people the founder says they mixed up with that employee. Both are evidence-checked against the founder's words. The reply is told both. A reply naming a mixed-up person fails the reply check (`wrong_person`): it is rewritten once with that reason, then replaced by the server's own text.

## 7. The checkpoint (`heroos.assistant-checkpoint/1`)

The checkpoint holds bounded codes only (8 KB at most): what HeroOS asked last, ENGINE_TRUSTED facts the Case doesn't hold, the jurisdiction answer, two-state cautions, `reconfirm`, the last evaluated decisions, voided Case facts, the Case revision, the knowledge and profile identity and **the Company jurisdiction** it was written under, and the **active reviews**. It is an optimization and a projection: with a Case, the Case's facts are authoritative and the checkpoint never duplicates them.

**It is rebuilt and re-confirmed, never trusted,** when it is missing, malformed, of an unknown schema, written under other knowledge, another execution profile or rule bundle, or another Company jurisdiction, or for another workflow. What is rebuilt is the workflow, the Case's facts **re-validated against the current runtime**, and the Case's jurisdiction answer. A stored value the current runtime no longer accepts stays history and is never used. Active reviews are history, not runtime state: they are kept whenever the checkpoint is readable, and replayed from the turn records otherwise (`Reviews.replay`).

## 8. Jurisdiction

- New turns use the current Blueprint; old messages and evaluations stay as they were.
- **A Blueprint jurisdiction change** invalidates the checkpoint (a rebuild and re-confirmation), so no trusted state crosses jurisdictions. A Case confirmation made under the earlier Company jurisdiction is outdated: it counts as "not sure" until it is confirmed again.
- **Unclear, conflicting or unconfirmed jurisdiction pauses only what depends on it** (JJ's rule): no requested decision gets a jurisdiction-specific result (each is held for the jurisdiction, `jurisdiction:<state>`), and the knowledge the model sees is retrieved again **shared guidance only** (`_for_employee`: no UAE Federal or DIFC text, and a note that jurisdiction-specific guidance waits). The approved runtime's shared and global content (the investigation methodology, shared Conditions) continues. Shared applicability is never inferred: options are always per jurisdiction in the approved content, so none continues on its own.
- **The Case is not frozen** for it: lifecycle stays `in_progress`, `attention.jurisdiction` is `needs_confirmation` and `attention.needs_information` is true. The structured stages wait too (every one belongs to one jurisdiction's programme in the rule bundle; the intake's `jurisdiction` hold, which the employer lifts by confirming one answer). Only a whole-matter hold pauses the Case (§9).
- An employee under **another** jurisdiction (`case_different`) or an unsupported one is a specialist-review matter: the intake's specialist-review hold, which does pause the Case.

## 9. Status

```text
status
├── lifecycle        in_progress / paused (the intake's specialist-review hold: the whole matter) / null (no Case)
├── workflow         {key, title} / null
├── attention
│   ├── needs_information   the latest turn's checks need an answer, or the jurisdiction does
│   ├── jurisdiction        needs_confirmation / null
│   └── expert_review       {active, scope: action | matter, actions (titles), service_available}
├── checks           ready / unavailable / not_applicable (the runtime as it is now)
└── latest_outcome   guidance / warning / block / expert_review / unavailable / none
```

- **Separate dimensions.** An action's Expert Review never pauses the Case (investigation Guidance and dismissal without notice under Expert Review: lifecycle `in_progress`). A Block is per action. Technical unavailability is `checks: unavailable`, never a lifecycle, and recovers with the runtime with no Case event. There is no closed, resolved, dismissed, approved, lawful or sanctioned lifecycle; nothing is inferred from "I'm happy, thanks", and "New conversation" closes and deletes nothing.
- **Expert Review, current and historical.** A decision's review stays active until a later evaluation of that decision no longer requires one, or the founder **explicitly withdraws** it. A withdrawal comes from the understanding's optional `withdrawn_actions`, kept only for the current message, in the founder's own words, with explicit withdrawal wording ("no longer considering", "decided against"…), and never for a decision the same message asks about. A turn about something else changes nothing. Historical review requirements stay in each turn's record and message, immutable. A matter-level review follows the current matter (an unsupported HR matter; any HR turn re-states it, a non-HR turn keeps it); a withdrawal never clears it.
- **The Expert Review service** (`service_available`) is a **current capability** (`status.expert_review_service_available()`, false until M2-NEW-09), never read from a record. Nothing says a review was submitted, notified or ticketed.

## 10. The Ask HeroOS page

The signed-in home stays JJ's minimal landing ("What can HR do for you today?" and one box). History is secondary:

- **History** (a quiet control under the box, and in the conversation's header) opens **Recent conversations**, a drawer (a bottom sheet on phones): safe titles (the Case's, else "Conversation"), "Case" or "No case", and when it was last active, never a message preview. A page at a time ("Show older conversations", the API's cursor). Choosing one reopens it.
- **Reopening.** The open conversation is in the address (`?conversation={id}`), so a reload, a later visit or a link brings it back from the API, never from browser memory. Its latest messages load first; "Load earlier messages" reads older ones a page at a time.
- **A Case's chat.** A Case Ask HeroOS opened shows "Your Ask HeroOS conversation" at the top of the Case page (administrators), linking to that conversation, where it is read and continued. The Case's guided conversation and "Decisions & history" stay the Case's own.
- **Case context** over a conversation with a Case: its title (linking to the Case), the lifecycle in words, and separate attention items ("Expert review required before dismissal without notice", "Jurisdiction to confirm", "Needs information"), with a technical note when the checks are unavailable. Each turn keeps its own outcome, per step (Guidance, Warning, Block, Expert Review side by side), never flattened into one badge.
- **Attribution.** Another administrator's messages are labelled "Another administrator", never "You", with no email or identity.
- **New conversation** clears the page only: nothing is stored until HeroOS answers, nothing is closed or deleted, and the Case, its facts, reviews and workflow are untouched.
- **A failed send** (the provider fails before a completed turn) puts the words back in the box; nothing was stored, so nothing appears after a reload. A deterministic safe fallback is a completed turn and is shown and stored normally.
- **A conflict** (another tab or administrator moved the conversation on): the page loads the latest, keeps the unsent words in the box and says briefly that the conversation was updated elsewhere; nothing is overwritten or sent twice.
- **Footer:** "HeroOS doesn't make employment decisions." No claim that the chat isn't saved, and no retention, deletion or provider promise.
- While HeroOS can't answer (the gateway off), a stored conversation can still be read; the box says HeroOS can't answer right now.
- The conversation's speaker is HeroOS; Hannah stays decorative on entry surfaces.

## 11. Scale

- **Indexes** (each access path is backed): a Company's conversations by `(company_id, updated_at, id)` (keyset pages); messages and turns by `(conversation_id, sequence)`; `(company_id, turn_key)`; a Case's conversation by `(company_id, case_id)` (unique); a turn's evaluation by `turn_id` and its messages by `(turn_id, role)`. There is no full-text or GIN index on HR text or the evaluation JSON.
- **Pages.** Conversations use a keyset cursor (`<microseconds>.<id hex>`; `updated_at` is stamped per turn to the microsecond). Messages are paged by sequence (`before`); messages appended later never move an older page. Both have bounded sizes, and the browser never loads a whole lifetime to reopen a conversation.
- **Bounded AI context.** History is not prompt context. A turn reads back the latest 12 visible messages; the gateway then keeps the current message and at most 6 earlier founder messages and 6 conversation turns, within its character budgets. Continuity comes from the Case's facts and the checkpoint, never from replaying the whole conversation. Tests run 12- and 14-turn conversations and check that every message is retrievable while the model sees only the window.

## 12. Privacy and boundaries

- **PRIV-010:** not a blocker for this persistence (owner decision): HeroOS keeps the user-visible conversation so authorized users can reopen it. Provider envelopes, prompts, reasoning and provider scratch state are never stored (tests check the stored rows).
- **Retention, deletion and PRIV-020** stay unresolved. There is no delete endpoint, expiry, cleanup or "clear history". Other production processing and activation gates are unchanged.
- **M2-NEW-08** (not started) and **M2-NEW-09** (the Expert Review service and its tickets; not started) are outside this work: here, Expert Review is only a requirement.
- No document functionality, no provider or Bedrock activation, no live AI call in any test.

## 13. Migration D6 and schema contract 9

D6 adds the four tables (including `withdrawn_actions`, a JSON array of at most 3 option ids) and two columns on `workflow_submissions`: `origin` (default `structured`) and `source_message_id`. It is additive: the M2-NEW-06 API (contract ≥ 8) keeps working on it. Same contract as D1 to D5: explicit `company_id`, Company-qualified foreign keys, a single `tenant_isolation` RLS policy, no cascade from Cases, conversations, turns or messages, no DELETE grant, nothing for the identity operator. The API requires contract ≥ 9; the operator CLI requires exactly 9.

**Downgrade.** It refuses (and rolls back) once any conversation or any assistant submission exists: roll forward instead. This is the D1 to D5 convention, because deletion is decided by PRIV-020. On an empty schema it drops the four tables and the two columns. On a database with real conversations, `alembic downgrade` stops with "Ask HeroOS conversations exist" and changes nothing. The e2e migration rehearsal covers D5 → the M2-NEW-06 API → D6 → the current API, both downgrade guards and a D6 backup restore; the backup/restore gate restores a stored conversation, its evaluation and an assistant-origin fact.

Deploy order: D6, then the API and the operator CLI, then the web app. The web needs the D6 API: the message contract changed.

## 14. Tests

- `tests/conversations/`:
  - `test_service.py`: creation, failures, idempotency, threshold, titles, facts, provenance, corrections, nothing raw stored;
  - `test_http.py`: the API: replay, revisions, another administrator and attribution, tenant isolation, every status dimension, withdrawal, matter-level review, outages, the service capability, jurisdiction changes (shared guidance continues, a jurisdiction-specific decision waits, the Case stays in progress), a Case's conversation, pagination, bounded context;
  - `test_reconciliation.py`: stricter, authoritative relaxation (Block → Guidance, Warning → Guidance), uncertainty that never relaxes (a fact made "Not sure", an unresolved jurisdiction under Expert Review, a Company jurisdiction change), what counts as uncertainty, runtime and profile changes, historical values, separate matters;
  - `test_rules.py`: withdrawal evidence, review folding and replay, status independence (a jurisdiction to confirm is attention, never a paused Case), the value-not-path fact rules;
  - `test_mutation.py`, `test_checkpoint.py`, `test_bridge.py`, `test_model_contract.py`.
- `tests/evaluation/test_golden.py`: an employee whose jurisdiction isn't confirmed gets shared guidance only.
- `tests/auth/test_gateway_api.py`, `test_gateway_evaluation_api.py`: the contract through the real application.
- Real PostgreSQL (`tests/tenant_isolation/`):
  - `test_assistant_conversations.py`, `test_gateway_routes.py`: RLS three ways, WITH CHECK, Company-qualified keys, append-only grants, database refusals, no cascade; no row locked while the model answers; API tenant isolation; concurrent first turns; D6 up and down;
  - `test_ask_scenarios.py`: the end-to-end scenarios A to L through the production application over HTTP, with a scripted model only.
- `tests/recovery/`: the D6 dataset (a conversation, its turn, messages and evaluation, an assistant-origin fact) restores identically, with RLS.
- Web: `lib/server/gateway-bff.test.ts` (send and reads, field by field, authority refused, a Case's conversation), `components/ask/ask-conversation.test.tsx` and `ask-history.test.tsx` (turn keys, revisions, retries, reopening, History, earlier messages, attribution, status dimensions, conflicts, new conversation), `components/cases/cases.test.tsx` (the Case's link), `security-boundaries.test.ts`.

## 15. M2-NEW-08 additions

- **The Case's position at every turn** (`app/conversations/progress.py`): read when the turn starts and again at commit under the instance lock. It gives the evaluation `CaseProgress` and the model a labels-only `case_progress`. It is part of the reply's signature, so a stage another administrator completes while HeroOS answers relaxes the result at commit, and the stale wording is replaced (§4).
- **Status `position`**: the recorded pathway (the employer's decision), the stage in progress or next, the transitions held for specialist review. The lifecycle is unchanged: an action's review never pauses the Case.
- **Hypothetical decisions** never become active reviews or carried actions. `Reviews.after` and `Reviews.replay` skip records marked `hypothetical`.
- **The chat-first Case.** The Case page no longer shows the guided conversation thread. "Continue with HeroOS" comes first, and the structured case details are folded until asked for. The Case's formal steps appear inline in Ask HeroOS (`CaseSteps`) through the Case's existing routes.
- **A greeting** gets a greeting: no model request, no Case.
