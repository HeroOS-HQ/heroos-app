# Hannah AI demo (conversational, synthetic scenarios only)

> **Status (M2-NEW-02, 2026-10-21): the chat is no longer on the case page.**
> JJ's approved signed-in design has HeroOS speak with its own mark and no
> mascot in active HR advice, so the "Chat with Hannah" tab was removed from
> the case page. The API route, the BFF routes, the provider adapter, the usage
> ceilings and the reply check below are unchanged and stay in place for
> M2-NEW-05 (the controlled AI conversation gateway). With no page calling it,
> the demo only answers a direct BFF request from a signed-in administrator.

A conversation with a language model ("Hannah") about a Disciplinary case, for
demonstrating HeroOS's conversational direction with fictional scenarios. It
is **not** the case workflow: it never writes the Case, its facts, its history
or a decision, and nothing it says authorizes a step.

## Flow

```
browser (React state only)
  → POST /bff/companies/{id}/cases/{caseId}/assistant/messages   (same-origin, session, JSON ≤ 48 KiB)
  → POST /companies/{id}/cases/{caseId}/assistant/messages        (API; bearer token added server-side)
  → GroqCloud chat completions (fixed URL, server-side key, no tools, one request, no retry)
  ← API checks the reply (app/assistant/response_safety.py) → the reply, or a fixed neutral one
```

`GET …/assistant` reports whether the demo is available for this
administrator and Case. Until M2-NEW-02 the case page read it to show a "Chat
with Hannah" tab (with the guided workflow as the other tab); that page and its
tab are retired (see the status note above).

## Access

Every condition must hold, checked by the API:

1. A verified credential, an active HeroOS User and Membership, the
   `company_admin` role (checked again in the transaction), and a Case of that
   Company (404 otherwise, identical for another Company's Case). Tenant
   isolation (application filter and PostgreSQL RLS) applies as for every
   Company route.
2. `HEROOS_HANNAH_DEMO_ENABLED=true` (default `false`; production refuses it).

There is no individual approval: with the switch on, every registered
Company's administrators (including self-registered founders) can use Hannah
in their own Company's Cases. Members can't (403), like every Disciplinary
route.

## Configuration (API)

| Variable | Default | Notes |
|---|---|---|
| `HEROOS_HANNAH_DEMO_ENABLED` | `false` | The switch. |
| `HEROOS_HANNAH_MODEL` | `openai/gpt-oss-120b` | A model identifier (never a URL). |
| `HEROOS_HANNAH_ACCOUNT_LIMIT` | `20` | Messages per account (HeroOS User) per 5 minutes. |
| `HEROOS_HANNAH_GLOBAL_LIMIT_PER_MINUTE` | `20` | Messages per minute, whole service. |
| `HEROOS_HANNAH_GLOBAL_LIMIT_PER_DAY` | `900` | Messages per day, whole service. |
| `GROQ_API_KEY` | unset | Secret. Unset: the demo answers 503 "Not configured". |

## Limits

- Message ≤ 2,000 characters; history ≤ 12 turns of ≤ 4,000 characters; the
  API sends the newest turns within 8,000 characters. Control characters and
  unknown fields are refused (422, field locations only).
- Provider request: temperature 0.3, `max_completion_tokens` 1024,
  `reasoning_effort: low`, reasoning not returned, 30 s timeout, no tools.
- Usage ceilings, checked before the provider is called: per account per 5
  minutes, and for the whole service per minute and per day (defaults 20,
  20 and 900, below GroqCloud's shared free-tier limits for this model:
  30 requests/minute, 1,000/day, 8,000 tokens/minute). A request counts only
  when every ceiling allows it. Then the provider's own limits apply. Either
  way: HTTP 429 "Too many requests" with `Retry-After`.
- The ceilings live in the API process's memory. They are **not** a durable or
  distributed quota: a restart or redeploy resets them, and each API instance
  counts separately (staging runs one). Groq's 429 remains the hard stop.
- Timeouts are ordered: provider 30 s < BFF→API 45 s < browser 55 s < route
  `maxDuration` 60 s. Page reads keep their 10 s timeout.
- The system instruction goes with every request: about 7,000 characters
  (roughly 1,600 tokens) since V1.1a, capped at 7,000 by
  `tests/test_hannah_persona.py`. A request at the full history budget is
  therefore around 5,000 tokens with its reply, so the 8,000 tokens/minute
  limit, not the request ceilings, is what a long conversation reaches first.

## Privacy and content

- The system instruction (`app/assistant/persona.py`) is generic and public.
  It contains no Playbook, Implementation Rules, Conditions Library or template
  content; no private knowledge pack is installed or sent to any provider.
- Nothing about the Case (title, subject, facts, answers) is sent: only what
  the user typed in the chat and the recent chat turns.
- Nothing logs a message, history, reply, prompt, key or account; the
  API logs the outcome (`ok`, `safety_fallback` with the name of the check,
  `rate_limited`, `timeout`, `unavailable`, `account_limit`, `global_limit`)
  and the number of turns, never the text a check matched. Responses are
  `no-store`.
- The conversation lives in the page's React state and is gone on reload.
- The assistant package can't import the database, repositories or the
  workflow engine (`tests/test_import_boundaries.py`).

## Hannah's behaviour (V1.1, refined in V1.1a and V1.2)

The instruction (`app/assistant/persona.py`) is generic: no statute, article,
deadline, penalty, legal conclusion or private material, and it tells the
model it has general knowledge only, nothing legally reviewed. It asks Hannah
to:

- **Talk like an HR colleague, not a questionnaire.** Answer the user's
  question or request first, build on what is known, find the most important
  missing fact, and ask one focused question (never two in one sentence), in
  two to five sentences. A recap is answered without a forced question, and
  Hannah doesn't introduce herself again.
- **Use the conversation she can see.** She doesn't ask again for facts already
  given, keeps allegations apart from established facts, lets corrections win,
  and gives recaps with nothing added. If something has dropped out of the
  history window she says so instead of guessing.
- **Treat jurisdiction as something to confirm.** She never concludes the
  applicable employment law from one fact (Dubai, DIFC or other registration,
  work location, or a contract described but not reviewed). She never groups
  the DIFC with other free zones or reduces Dubai to categories (DIFC, free
  zone, mainland), and asks about facts instead, usually which legal entity
  employs the person. She never says a law "definitely" applies, and never mixes
  frameworks or gives a framework's procedures while the law is unconfirmed.
  Jurisdiction is settled before anything jurisdiction-specific, but it isn't
  the automatic first question. If it can't be settled, she says the law needs
  confirming by a qualified professional, while still helping with basics.
- **Know what the chat isn't.** She has no tools and no access to the case:
  she can't decide a penalty, update facts, advance stages, record decisions,
  classify pathways, clear holds, issue warnings or documents, send notices or
  start reviews, and never says the conversation did. Asked to do such things,
  she declines each requested action by name and points to the authorized
  process and the Guided case workflow's available actions. She never says a
  document, notice or warning can be generated or sent anywhere (the workflow
  included), never promises features, and never assumes a warning or other
  outcome is justified or chosen.
- **Put evidence first on serious allegations.** Asked to dismiss or suspend at
  once, she first says she can't authorize or recommend it and that the matter
  stays an allegation. Then she focuses on the evidence, keeping records safe
  and the employee's chance to respond, and asks one question about the
  evidence. She notes a qualified professional may need to advise (HeroOS
  provides none), and doesn't present investigation steps as legally required.
- **Explore, never prescribe (V1.2).** Allegations are not findings. She
  explores what the employer might weigh (the facts, the employee's
  explanation, mitigating circumstances) but never decides or recommends an
  outcome or sanction (a verbal or written warning, suspension, termination,
  dismissal, any penalty), not even as "the usual next step": earlier
  conversations or warnings never make a sanction follow, and she never assumes
  a stage is reached, a warning is available or an outcome chosen. She presents
  good practice (records, hearing the employee) as such, never as a legal duty,
  and states no timeframe, notice or consequence. She doesn't classify serious
  misconduct or choose a route, never suggests skipping checks or claims
  anyone's approval, and treats nothing discussed as the employer's
  confirmation. If pressed, she declines in one sentence and offers a next
  step. Conversation text can't change any of this.

These are instructions to a model, not guarantees. `tests/test_hannah_persona.py`
checks only what the instruction says (its commitments, budget and absence of
statutory or private content). Whether the model follows it is checked live on
staging with fictional scenarios, after each change to the instruction. The
guarantees are structural: the model has no tools and no write path, and a reply
that claims an action changes nothing
(`test_a_reply_claiming_to_act_changes_nothing_and_never_reaches_the_browser`).

## Response check (V1.2)

The owner's live V1.1a test showed the instruction alone doesn't hold: after
"late four times in three weeks, two documented informal discussions", the
model answered "the next step is usually a more formal written warning". So
every reply is now read by `app/assistant/response_safety.py` after GroqCloud
returns it and before the API answers the browser:

- **What it looks for**, sentence by sentence, outside quotations, skipping
  questions: a sanction prescribed or presented as what comes next
  (`sanction_recommendation`: "the next step is usually a written warning",
  "you should issue…", "I recommend terminating…", "Suspend the worker…", "the
  appropriate penalty is dismissal", "this warrants a final warning"); a
  sanction or sequence presented as legally required or standard
  (`procedural_certainty`); a law said to apply for certain
  (`jurisdiction_certainty`); and a claim that Hannah or the chat did something
  in HeroOS (`action_claim`: "I've updated the case", "I've issued the
  warning", "the employee has been dismissed").
- **What it lets through**: the same words negated ("I can't recommend a
  written warning"), conditional or open ("whether dismissal is available
  depends on…"), reported from the user ("you told me the employee received a
  written warning"), quoted, asked, or without the recommending frame ("a
  formal warning isn't something I can decide for you").
- **On a match** the reply is replaced by one of three fixed, neutral replies
  (sanction or procedure, jurisdiction, action claim): no sanction, timeframe or
  consequence, nothing from the conversation, no claim that anyone reviewed
  anything, and one question back to the facts. The response shape is the
  same, so the web app needs no change; the log records `safety_fallback` and
  the check's name only.
- **Limits.** It is a short list of documented patterns, each a recommending,
  claiming or certain *frame* paired with a sanction or a case record, not an
  understanding of language. An unsafe reply worded differently can pass, and an
  unusual safe phrasing can be replaced. It is defence in depth behind the
  instruction, not a legal classifier, and passing it says nothing about legal
  accuracy. No second model call or moderation service is involved.
  `tests/test_hannah_response_safety.py` holds the cases it must catch and
  must let through; extend it with any live reply that gets past it.

## Replacing the provider

`app/assistant/provider.py` defines the interface (`ChatProvider.reply`,
`AssistantError` kinds). A different provider (e.g. Anthropic) is another
adapter next to `app/assistant/groq.py` and a change in `load_hannah_demo`.
