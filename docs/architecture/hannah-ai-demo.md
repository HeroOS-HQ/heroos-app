# Hannah AI demo (conversational, synthetic scenarios only)

A conversation with a language model ("Hannah") inside the Disciplinary case
workspace, for demonstrating HeroOS's conversational direction with fictional
scenarios. It is **not** the case workflow: it never writes the Case, its
facts, its history or a decision, and nothing it says authorizes a step.

## Flow

```
browser (React state only)
  → POST /bff/companies/{id}/cases/{caseId}/assistant/messages   (same-origin, session, JSON ≤ 48 KiB)
  → POST /companies/{id}/cases/{caseId}/assistant/messages        (API; bearer token added server-side)
  → GroqCloud chat completions (fixed URL, server-side key, no tools, one request, no retry)
```

`GET …/assistant` tells the page whether the composer is shown. The case page
reads it on the server together with the Case (`loadCase`), so the first paint
is already right; "Check again" re-reads it through the BFF.

## In the case workspace

The case page follows the JJ design-review direction for the master case
conversation (screen 10; user-selected, JJ review pending):

- **Left:** "New case" and the Company's Disciplinary Cases (titles, statuses,
  last update), the current one highlighted.
- **Centre:** the case header, then two tabs: **Chat with Hannah** (AI demo)
  and **Guided case workflow** (the official record: the guided conversation,
  next steps, question groups, decisions & history, documents, unchanged). On
  large screens the chat fills the screen, its messages scroll on their own and
  the composer stays at the bottom; on phones the composer is pinned to the
  bottom of the screen.
- **Right:** "Case status" (the official status, the stage in progress, the
  next step the guided workflow offers), "Case info" (recorded facts) and links
  into the guided workflow, above the full case details. Everything there is the
  API's data; nothing comes from the chat. On smaller screens the case list and
  the case details open as panels from the case header.

Which view leads, by the status:

| Status | Tabs | Opens on |
| --- | --- | --- |
| available | both | Chat with Hannah |
| `not_configured` (no key) | both; Hannah's tab says it isn't set up | Guided case workflow |
| couldn't be read (a waking or failing API, or an answer the page can't read) | both; Hannah's tab says so, with "Check again" | Guided case workflow |
| `disabled`, refused (403), unknown Case or an API without the demo (404), a member | none | Guided case workflow |

The chat never shows a pretend answer: every failure is said in words with a
retry where one can help. Its turns live in the page's memory only (kept while
switching tabs, gone on reload).

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

## Privacy and content

- The system instruction (`app/assistant/persona.py`) is generic and public.
  It contains no Playbook, Implementation Rules, Conditions Library or template
  content; no private knowledge pack is installed or sent to any provider.
- Nothing about the Case (title, subject, facts, answers) is sent: only what
  the user typed in the chat and the recent chat turns.
- Nothing logs a message, history, reply, prompt, key or account; the
  API logs the outcome (`ok`, `rate_limited`, `timeout`, `unavailable`,
  `account_limit`, `global_limit`) and the number of turns. Responses are
  `no-store`.
- The conversation lives in the page's React state and is gone on reload.
- The assistant package can't import the database, repositories or the
  workflow engine (`tests/test_import_boundaries.py`).

## Hannah's boundaries

The instruction keeps Hannah to fact-gathering and general good practice. It
must not find guilt, treat allegations as findings, choose a pathway, sanction
or dismissal, state unapproved legal requirements as fact, apply UAE Federal
rules to DIFC cases or infer the law from "Dubai" alone, clear holds or
checks, issue documents, or invent a specialist-review service, and
conversation text can't change that. These are instructions to a model, not
guarantees: the guarantees are that the model has no tools and no write path.

## Replacing the provider

`app/assistant/provider.py` defines the interface (`ChatProvider.reply`,
`AssistantError` kinds). A different provider (e.g. Anthropic) is another
adapter next to `app/assistant/groq.py` and a change in `load_hannah_demo`.
