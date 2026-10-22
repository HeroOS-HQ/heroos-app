# Ask HeroOS: the controlled AI conversation gateway (M2-NEW-05)

The founder explains a situation in their own words on Ask HeroOS. HeroOS
makes sense of it, works out what HeroOS's **approved knowledge** says about
it, and answers: what the approved methodology says applies, what it still
needs to know (asked naturally, one thing at a time), and which requested
actions need specialist review. No Case is needed to ask.

**Since M2-NEW-07** the conversation is persistent: the API stores the visible
conversation, attaches a Case once the matter is clear, and takes the trusted
state from the server instead of the browser. The message contract in §3, §8
and §16 below is the M2-NEW-05/06 one, kept for history; the current contract
is in [ask-conversations.md](ask-conversations.md).

The gateway is **off by default** and stays unavailable until every
activation prerequisite below holds. While it is unavailable, Ask HeroOS
works exactly as before (M2-NEW-02): Send opens a guided Disciplinary case.

- Code: `apps/api/app/assistant/gateway/` (orchestration), `apps/api/app/api/gateway.py`
  (routes), `apps/api/app/assistant/groq.py` (provider adapter),
  `apps/api/app/assistant/response_safety.py` (reply checks).
- Web: `components/ask/ask-conversation.tsx`, `lib/ask/conversation.ts`,
  `POST /bff/companies/{id}/assistant/messages`.
- Related: [conversation-evaluation.md](conversation-evaluation.md) (M2-NEW-06:
  the deterministic outcome each turn now carries),
  [knowledge-runtime.md](knowledge-runtime.md) (the only HR/legal
  authority), [company-blueprint.md](company-blueprint.md) (the only company
  context), [signed-in-workspace.md](signed-in-workspace.md) (Ask HeroOS),
  [hannah-ai-demo.md](hannah-ai-demo.md) (the legacy demo this supersedes).

## 1. The one rule: the knowledge runtime is the authority

Everything HeroOS says about HR or employment law comes from
`app.knowledge.get_knowledge_context(...)` on the installed, validated
knowledge bundle (M2-NEW-04). The gateway never reads the source documents,
the compile mapping, the validation report, a workbook, a template, the open
web or a model's general knowledge, and it never "improves" a status the
runtime returns (`unsupported`, `source_conflict`, `review_required`,
`jurisdiction_unresolved`, `bundle_unavailable`, `needs_more_context`). It has
no library-specific logic: what a document, Condition or option means is
whatever the bundle says.

## 2. What it does and doesn't do

| Does | Doesn't (owner) |
| --- | --- |
| Accept free text, with no Case and nothing to choose | Evaluate a Condition, or decide WARN / BLOCK / ESCALATE / ALLOW (done by M2-NEW-06's deterministic evaluator, never by the model) |
| Propose a candidate workflow, pathway and topics from the bundle's own catalog; unresolved is valid | Create or change a Case, workflow, fact, decision or history (M2-NEW-06/07) |
| Keep the founder's explicit statements as facts for this turn, with evidence | Persist the conversation, its facts or provenance (M2-NEW-07) |
| Query the runtime narrowly, server-side | Choose the Guidance / Warning / Block / Expert Review outcome (M2-NEW-06's server-owned card; the model only phrases it) |
| Choose what to ask next (server) and let the model phrase it | Generate or offer a document (M2-NEW-08) |
| Explain approved options as possibilities the employer decides on | Create or promise an Expert Review (M2-NEW-09) |
| Say when an action needs specialist review, and keep going with the methodology that still applies | Fetch the company website, browse or search (future, separately controlled) |
| Fail closed, and hand a clean understanding to the next layer | Decide misconduct, choose a sanction, approve a dismissal |

**The 05 / 06 split.** Here, Conditions only shape the conversation: which
facts matter, what must be clarified, what must not be said, which safeguards
come first. Nothing here concludes that a Condition fired. Since M2-NEW-06,
the deterministic evaluator (`app/evaluation`, [conversation-evaluation.md](conversation-evaluation.md))
runs between retrieval and the response: explicitly bound rules on
server-trusted facts only, action by action, never the whole conversation.

## 3. One founder turn

(M2-NEW-05/06. Since M2-NEW-07 the browser sends only its words, a turn key, the conversation
and its revision, and the reply is stored: [ask-conversations.md §3](ask-conversations.md).)

```
browser (React state only: the conversation is never stored)
  → POST /bff/companies/{id}/assistant/messages     (same-origin, session, JSON ≤ 48 KiB, rebuilt field by field)
  → POST /companies/{id}/assistant/messages          (API; bearer token added server-side)
      1. credential → active Membership → company_admin (re-checked in a read-only transaction)
      2. load_company_blueprint_context(...)  → release the database connection
      3. readiness (no model request otherwise) → usage limits
      4. UNDERSTANDING   model request #1 (+ at most one schema repair)
      5. evidence check, routing without a model for out-of-scope requests
      6. get_knowledge_context(...)  → server-chosen question targets
      7. GROUNDED RESPONSE   model request #2 (+ at most one schema repair)
      8. grounding check + reply-safety check → the reply, or a reply the server composes
  ← {reply, safe_next_step, conversation_state, continuation}
```

At most **four** provider requests per founder turn, inside one 40 s budget
(each request at most 20 s). A provider failure is never retried and never
answered by anything else.

## 4. Access

All before any model request, through the same chain as every
administrator route (`CompanyAdminReadOnlyDb`):

1. a verified credential, an active HeroOS User and Membership;
2. the `company_admin` role, checked again inside the transaction;
3. tenant isolation (application filter and PostgreSQL RLS); another
   Company's id answers exactly like an unknown one (403);
4. a transaction that refuses every write;
5. the canonical `CompanyBlueprintContext` (an ended Membership is 403).

The client chooses nothing but its words: unknown fields (a provider, model,
URL, jurisdiction, company, case or workflow) are refused with 422.

## 5. Company context

`load_company_blueprint_context` only. The model sees a whitelisted view
(`projection.company_view`): industry, number of employees, company summary,
whether the employment jurisdiction is confirmed (and which), HR policies,
policy notes, HR support and notes. Never ids, people, roles, dates, the
licensing answer, audit fields or the website (stored only; never fetched).

## 6. Understanding (phase A)

Input: the fixed instruction (`prompts.UNDERSTANDING_INSTRUCTION`), the
**routing catalog** built from the installed bundle (`catalog.py`: workflows,
pathways and topics as keys and titles, extractable facts as keys and
labels), the company view, what HeroOS last asked about (see §8) and the
founder's own recent messages, numbered. **Never HeroOS's earlier replies.**

Output, strictly validated (`proposals.parse_understanding`):

```
{"schema_version": "heroos.understanding/1",
 "intent": "supported_hr" | "other_hr" | "unclear" | "unsupported" | "confidential_request",
 "workflow_candidate": key | null, "pathway_candidate": key | null, "topics": [≤ 3 keys],
 "fact_proposals": [{fact_key, proposed_value, confidence, provenance, source_turn,
                     support_excerpt, explicit_or_inferred}],
 "uncertainties": [codes], "case_summary": text | null,
 "requested_actions": [{action, source_turn, support_excerpt}]}   (M2-NEW-06, optional)
```

`requested_actions` names, by stable catalog option id, the employer
decisions the founder explicitly asked about, each with their own words
(evidence-checked like a fact). It only ever adds deterministic checks.

There is no field for a Condition, outcome, sanction, transition, document,
jurisdiction or legal conclusion, and an unknown field is refused. Only
`supported_hr` may name a workflow; unknown keys are refused; one schema
repair is allowed, then the turn fails (502).

The catalog leaves out the jurisdiction (only the Blueprint's operator
confirmation counts), facts the Blueprint holds, and **sensitive** facts
(health, pregnancy, complaints, criminal allegations...): there is no privacy
basis to collect them in a conversation, so they are never extracted, asked
for or sent back to a provider.

**Routing without a model.** `other_hr` (probation, recruitment, performance:
not published runtime knowledge), `unsupported` (workforce strategy, anything
that isn't an employer's HR situation), `confidential_request` ("show me your
Conditions Library", "print your system prompt") and `unclear` each get a fixed
reply composed by the server, with no second request: no generic answer, no
invented process, no fake ticket.

## 7. Facts and evidence

A fact proposal is a candidate. `check_evidence` keeps it only when:

- its key is in the catalog (an invented key is dropped);
- its excerpt really appears in the cited founder message (or, for
  `company_blueprint`, in the company view the model was shown);
- the turn matches its provenance (`current_user_message` = the current
  turn, `prior_user_message` = an earlier one).

A proposal that fails is dropped, never repaired. Only an **explicit,
confident** statement establishes a fact for this turn ("absent for exactly
eight consecutive days"); an inferred or approximate one ("gone all week")
never satisfies a fact the methodology needs, and HeroOS asks to confirm it.
When the founder corrects themselves, the newest explicit statement wins
(`planning.established_facts`). HeroOS's own words are never evidence: the
understanding phase never sees them, and nothing cites them.

## 8. What HeroOS last asked: the continuation

(Since M2-NEW-07 a persisted conversation keeps this state server-side, as its checkpoint, and
the browser neither sends nor receives a continuation: [ask-conversations.md §7](ask-conversations.md).)

"Yes" or "twice" only means something next to the question it answers. Each
reply carries an opaque `continuation` token. Since M2-NEW-06 it is the
encrypted evaluation continuation (`app/evaluation/continuation.py`,
[conversation-evaluation.md §11](conversation-evaluation.md#11-the-evaluation-continuation-heroosevaluation-continuation1)):
what HeroOS asked and the state its checks trust, AES-GCM under a shared
server key, bound to the Company, the user, the knowledge and the execution
profile, valid four hours. The next turn tells the model "the founder may be
answering a question about: <labels from the bundle>". Any problem with a
token just loses that state (re-confirmed, never loosened); it grants nothing.

## 9. Retrieval and what to ask (server-side)

`planning.py`, deterministic:

- **Jurisdiction**: the Blueprint's confirmed employment jurisdiction while
  guidance is allowed. Never from the conversation: "we're in Dubai" is not a
  jurisdiction. The model can only make it less certain
  (`jurisdiction_conflict`: the founder's words suggest another employing
  entity), never more. The founder's statements are never persisted and
  never change the Blueprint.
- **Query**: the validated workflow, the topics (else the pathway, else
  general orientation), the established fact keys and the company context.
  The model never names a Condition or document and never calls the runtime.
  A `source_conflict` on one of several topics leaves only that topic out.
- **Question targets**: the facts the approved methodology still needs, in the
  runtime's order, safety first (tier 0 safeguards bearing on the request,
  then the methodology, then the decisions asked about, then what a
  specialist would need for a decision held for review, then the rest). One
  target by default; a second only when the same approved item needs it.
  Never a document gate (document preparation is not part of this
  conversation), a sensitive fact, a Blueprint fact or something answered.
- **Requested actions**: the decisions linked to the topics asked about, with
  the runtime's availability (`supported`: still the employer's decision,
  after every required step; `review_required`; `not_available`). This is how
  review stays **action-scoped**: "dismissal without notice needs specialist
  review" while the investigation methodology continues.

| Knowledge status | What HeroOS does |
| --- | --- |
| `bundle_unavailable` | No model request at all; 503 `Knowledge unavailable` |
| `unsupported` | Fixed reply: not covered by approved guidance; specialist advice |
| `source_conflict` | Fixed reply: can't safely guide that route; specialist advice |
| `jurisdiction_unresolved` | Shared orientation the runtime marks safe; says what confirming the jurisdiction needs |
| `review_required` | Approved methodology continues; the held actions are named as needing specialist review |
| `needs_more_context` | Asks the server's highest-priority question |
| `supported` | Concise approved guidance; never "allowed", "lawful" or "recommended" |

## 10. Grounded response (phase B)

Input: the fixed instruction (`prompts.RESPONSE_INSTRUCTION`), the
**minimized knowledge view** (`projection.knowledge_view`), the company view,
the established facts (labels and values), a jurisdiction note, the recent
conversation and the current message, all as data in one JSON message.

The knowledge view holds only what the reply needs: approved guidance and
caution texts with titles, how each may be presented (a Condition whose
legal basis isn't confirmed is "a practical caution, never the law"), the
decisions with their availability, the behaviors HeroOS must keep and must
never adopt (in words), the limitations and the question targets (`q1`,
`q2`). Never: source references, file names, hashes, digests, item ids, raw
Condition rows, triggers, not-enforced or withheld Conditions, validation
findings or templates. Document codes inside approved text become the
documents' titles. A 9,000-character budget keeps it small, and the view
says when more approved material exists than it shows.

Output, strictly validated (`proposals.parse_response`):

```
{"schema_version": "heroos.response/1", "reply": "...", "question_target_ids": ["q1"],
 "safe_next_step": "..." | null}
```

No status, review flag, outcome, jurisdiction, reference or digest can be
returned. One schema repair; a second invalid output is replaced by a reply
the server composes (§11).

## 11. Checks on every reply

Defence in depth behind the instructions. Neither check is a legal
classifier; both read the reply and the safe next step.

**Grounding** (`grounding.py`): an article, law or decree number not in the
approved view (a founder's claimed article never counts); a number of days,
weeks, months, years, a percentage or an amount not in the approved view
unless said back as the founder's own; another regime's named authority
(or any, while the jurisdiction is unresolved); an internal identifier of the
installed bundle or a rule number; any amount, percentage or limit next to a
deduction where the runtime forbids calculating or recommending one; a long
passage copied from the approved material or from the instructions.

**Reply safety** (`response_safety.gateway_problem`): Hannah's four checks
(recommended sanction, procedural certainty, jurisdiction certainty, claimed
action) and five more: authorizing a sanction or deduction ("you can dismiss
her today", "dismissal without notice is available"), promising specialist
review ("I've sent this to a HeroOS Expert", "your ticket has been
created"), promising to monitor or remind, claiming a document was prepared,
and stating the law as certain ("by law you must", "secret recording is
illegal", "you always need consent"). Explaining an approved option stays
allowed ("suspension may be one of the options the approved process considers
after the investigation").

A failing reply is replaced by one the server composes from fixed text and
the plan: a fixed lead, the held actions ("… needs specialist review before it
is taken"), the jurisdiction prerequisite, and the first question target as a
plain question. No model text survives.

## 12. Provider

The existing `ChatProvider` abstraction is extended, not replaced:
`StructuredChatProvider.complete_json(system, turns, *, temperature,
max_completion_tokens, timeout) -> Completion` (text plus reported token
usage). The GroqCloud adapter implements it on its fixed HTTPS endpoint with
`response_format: json_object`, a server-side key, no tools, no browsing, no
retrieval, refused redirects, and clamped temperature (≤ 0.3), completion
budget (≤ 2,048 tokens) and timeout (≤ 30 s). The gateway asks for
temperature 0.0 (understanding) and 0.2 (response), 1,200 tokens each.
Provider and model are server configuration only. There is no automatic
fallback to another provider. Changing either (or the model's version) is a
controlled change, evaluated before it serves founders (§13). CI uses a
scripted fake (`tests/fixtures/gateway.py`).

**Automated tests never reach a real provider** (`app/assistant/live.py`,
added in the M2-NEW-05 closeout after a test harness left the gateway enabled
with a placeholder key and one synthetic message reached GroqCloud). Whether a
process may call the real provider doesn't depend on the gateway, demo or key
settings at all:

- a deployed environment (staging, production) that isn't a test run may;
- an automated test run (pytest is loaded, or `HEROOS_AUTOMATED_TEST=true`,
  which the end-to-end harness sets on every API it starts, after any suite's
  own settings) and local development never may;
- a deliberate local live smoke test opts in with
  `HEROOS_AI_LIVE_SMOKE_ENABLED=true` (refused in production).

Where calls aren't allowed, the gateway and the Hannah demo get an
`OfflineProvider` (the configuration still reads as configured, so pages can
be tested) and every request fails as `unavailable` with no network access.
The real transport checks again before every request, so a provider built
any other way inside a test run can't call out either
(`tests/assistant/test_live_calls.py`).

## 13. Configuration and activation

| Variable | Default | Meaning |
| --- | --- | --- |
| `HEROOS_AI_GATEWAY_ENABLED` | `false` | The switch |
| `HEROOS_AI_GATEWAY_PROVIDER` | unset | `groq` (the only adapter) |
| `HEROOS_AI_GATEWAY_MODEL` | unset | A model identifier, never a URL |
| `GROQ_API_KEY` | unset | Server-side secret (shared with the Hannah demo) |
| `HEROOS_AI_GATEWAY_APPROVAL` | unset | Reference of HeroOS's approval of this deployment's AI configuration (provider, data protection terms, environment), e.g. a privacy decision id |
| `HEROOS_AI_GATEWAY_ALLOW_DEVELOPMENT_KNOWLEDGE` | `false` | Allows a bundle that is development or synthetic content; production refuses it |
| `HEROOS_AI_GATEWAY_ACCOUNT_LIMIT` | 10 | Founder turns per account per 5 minutes |
| `HEROOS_AI_GATEWAY_GLOBAL_LIMIT_PER_MINUTE` | 6 | Founder turns per minute, whole service |
| `HEROOS_AI_GATEWAY_GLOBAL_LIMIT_PER_DAY` | 300 | Founder turns per day, whole service |
| `HEROOS_AI_LIVE_SMOKE_ENABLED` | `false` | A local live smoke test's explicit opt-in to real provider calls from development or a test run; refused in production (§12) |
| `HEROOS_AUTOMATED_TEST` | `false` | Marks an automated test run: no real provider calls (set by the e2e harness; pytest is detected) |

Plus an installed knowledge bundle (`HEROOS_KNOWLEDGE_BUNDLE_PATH` and
`_SHA256`, knowledge-runtime.md §14). Enabled with anything missing, the
gateway stays unavailable (`GET …/assistant` says `not_configured` or
`knowledge_unavailable`; startup logs `missing=…` names, never values) and
Ask HeroOS opens cases as before. Production additionally refuses a
development bundle at load (M2-NEW-04): development content can't silently
become production content.

**Privacy and activation gate.** Enabled, the gateway sends a founder's
words, the company view and normalized approved knowledge for this turn to
the configured provider. It never sends the source documents, the mapping,
the validation report or the bundle itself.

Real customer use needs three kinds of approval, each from its own authority:

- **Technical authority** (the Technical Lead): the provider and model
  architecture and the exact runtime configuration tested for activation,
  after the exact-model evaluation below.
- **Product / domain authority** (JJ): HeroOS's methodology, approved
  content and business behavior, including an approved knowledge bundle.
- **Legal / privacy authority**: whether the data processing is acceptable.
  That covers the provider and model, training and data use, retention,
  processing location and input data categories: PRIV-009, PRIV-010,
  PRIV-011, PRIV-012 and PRIV-021 in `docs/privacy/decision-register.md`.

The register still records those privacy decisions as open. A technical
direction has since been given in conversation and isn't in the register
yet, so it doesn't satisfy this gate:

- PRIV-009: a production direction is set, but the exact model isn't final;
- PRIV-010: minimal or zero provider retention;
- PRIV-011: no provider or base-model training on HeroOS customer HR data;
- PRIV-012 and PRIV-013 are deferred.

Customer use also needs the provider's business terms and the third-party
inventory entry.

Until all of that is in place, only synthetic testing in a non-production
environment is allowed, with `HEROOS_AI_GATEWAY_APPROVAL` naming the
authorization for that test. The page shows the API's notice ("use
fictional scenarios only") while the knowledge is development content.

**Exact-model validation; a model change is a controlled change.** CI's
scripted provider proves the deterministic safety and integration behavior.
It doesn't prove a live model's conversational quality. Different providers,
models, versions, revisions and inference settings differ in:

- intent and requested-action recognition;
- structured extraction and output reliability;
- ambiguity and clarification handling;
- grounding, wording and latency.

Before an external production model serves founders, its exact configuration
goes through HeroOS's conversational regression evaluation. The same applies
before any replacement, whether a new version of the same model, another
model of the same family, or another provider. Normal CI never calls a live
model. The evaluation contract, its three layers and the runtime identity the
evaluation records are in
[conversation-evaluation.md §14.2](conversation-evaluation.md#142-production-model-and-provider-validation).
Deterministic outcomes stay authoritative and model-independent throughout.

**Token budget.** A founder turn is roughly 4–8K tokens across both phases
with the current bundle. That doesn't fit a free tier with an 8K tokens per
minute ceiling: staging verification needs a paid tier, or turns will fail
with 429.

## 14. Usage limits

`app.assistant.limits.UsageLimits` (shared with the demo, separate counters):
per account and service-wide, in this process's memory. They are abuse and
cost ceilings, not a commercial allowance (no "questions per year" product
rule exists or is implied). A restart resets them; staging runs one instance.

## 15. Logging

One line per founder turn, operational facts only: provider, model, outcome,
request count, repairs, knowledge status, runtime bundle digest, safety and
grounding outcome, facts dropped, token usage, latency, plus the request id
the observability layer adds. Never a message, history, fact, reply, prompt,
knowledge text, excerpt, key or personal data. Provenance (the runtime bundle
digest) stays server-side: it is not sent to the browser.

## 16. Browser contract and UI

(M2-NEW-05/06; superseded by the persistent contract in [ask-conversations.md §2](ask-conversations.md).)

`POST /companies/{id}/assistant/messages`:

- in: `{message (≤ 2,000), history (≤ 12 turns, ≤ 4,000 each), continuation?}`;
- out: `{reply, safe_next_step, conversation_state, outcome, continuation}`;
- `conversation_state`: `responded`, `clarifying` or
  `outside_approved_guidance`: how the turn was handled, deliberately not an
  outcome;
- `outcome` (M2-NEW-06): the server's deterministic card, or null
  ([conversation-evaluation.md §12](conversation-evaluation.md#12-browser-contract-and-ui));
- errors: 401 / 403 / 404 (disabled) / 422 / 429 (+`Retry-After`) / 502 / 503
  (`Not configured`, `Knowledge unavailable`) / 504, fixed details only.

`GET /companies/{id}/assistant` → `{available, reason, notice}`; the Ask page
reads it server-side (`loadAskGateway`) and shows the conversation only when
`available`.

The conversation (`ask-conversation.tsx`) keeps the approved landing ("What
can HR do for you today?"), then a thread with the composer docked below:
free text always, Ctrl/⌘+Enter to send, a loading state, a recoverable
error that keeps the typed message in the box, "New conversation", and a
note that the conversation isn't saved. Since M2-NEW-06 a turn with a
deterministic outcome shows it in JJ's approved tones (Guidance, Warning,
Block, Expert Review; words and an icon, never colour alone); the box stays
free in every state. An optional "Safe next step" is a practical step, never
a decision. No suggestion chips. Navigation is unchanged.

## 17. The handoff to M2-NEW-06 and M2-NEW-07

`service.Handoff` (server-side; not stored, not sent to the browser):
intent, workflow, pathway candidate, topics, established facts (key, value,
provenance, turn), tentative fact keys, uncertainties, case summary,
knowledge status, jurisdiction, actions held for review, what was asked and
the runtime bundle digest; since M2-NEW-06 also the requested action ids and
the deterministic `ConversationEvaluation` (its `record()` is the versioned
contract M2-NEW-07 may persist after re-evaluating it server-side). Since
M2-NEW-07 it also carries the turn's execution snapshot, and `GatewayReply`
the next trusted state (`next_state`), both server-side only, for the
persistence in [Ask HeroOS Conversations](ask-conversations.md).

## 18. The legacy Hannah demo

The case-scoped demo (`/companies/{id}/cases/{case}/assistant`) is
unchanged and still needs its own switch; no page calls it. The gateway
reuses its infrastructure (the provider adapter, usage limits, the reply
check, the timeout and error handling) and supersedes its behavior: HeroOS,
not Hannah, at Company level, on approved knowledge only, and allowed to
explain approved options.

## 19. Tests

- `tests/assistant/test_gateway_golden.py`: the golden conversations A–S.
- `tests/assistant/test_gateway_proposals.py`: the catalog, strict schemas, evidence.
- `tests/assistant/test_gateway_planning.py`: jurisdiction, facts, question targets,
  action-scoped review, the minimized view, source conflicts.
- `tests/assistant/test_gateway_checks.py`: grounding, reply safety (true and
  false positives), the continuation token.
- `tests/assistant/test_gateway_service.py`: readiness, limits, repairs, the
  call ceiling, provider failures, the time budget, layering, logs, the handoff.
- `tests/assistant/test_gateway_configuration.py`: settings, startup, the JSON request.
- `tests/assistant/test_live_calls.py`: stale gateway, demo and key settings
  never reach the network; the transport refuses inside a test run; only the
  live smoke opt-in builds the real provider; the e2e harness marks its APIs.
- `tests/auth/test_gateway_api.py`: the routes through the real application.
- `tests/assistant/test_real_bundle.py`: generic checks on the real bundle
  (local only: `KNOWLEDGE_BUNDLE=… uv run pytest tests/assistant/test_real_bundle.py`).
- `tests/test_import_boundaries.py`: no write path, no network, no knowledge route.
- Web: `components/ask/ask-conversation.test.tsx`, `lib/server/gateway-bff.test.ts`.

These prove what the server enforces whatever a model proposes. They don't
prove a live model's quality: that needs supervised synthetic testing once
the gateway is activated (§13).

## 20. Known limitations

- The checks are patterns: a reply can be unsafe in a way no pattern names,
  and an unusual safe phrasing can be replaced.
- Bounded history: a fact said long ago may fall out of view; HeroOS then
  asks again rather than guessing.
- Without `HEROOS_EVALUATION_CONTINUATION_KEY`, the continuation key lives in
  one process and carries only what HeroOS asked: after a restart HeroOS may
  ask a question again (M2-NEW-06 adds the shared key for trusted state).
- One provider adapter (GroqCloud); another provider is another class with
  the same shape.
