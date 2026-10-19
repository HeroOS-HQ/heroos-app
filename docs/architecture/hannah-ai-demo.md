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

`GET …/assistant` tells the page whether the composer is shown.

## Access

Every condition must hold, checked by the API:

1. A verified credential, an active HeroOS User and Membership, the
   `company_admin` role (checked again in the transaction), and a Case of that
   Company (404 otherwise, identical for another Company's Case).
2. `HEROOS_HANNAH_DEMO_ENABLED=true` (default `false`; production refuses it).
3. The caller's verified identity subject (the token's `sub`, exactly) is in
   `HEROOS_HANNAH_TESTER_SUBJECTS` (comma-separated). An empty or missing list
   admits no one, so a self-registered founder (an administrator of their own
   new Company) can't reach the model.

## Configuration (API)

| Variable | Default | Notes |
|---|---|---|
| `HEROOS_HANNAH_DEMO_ENABLED` | `false` | The switch. |
| `HEROOS_HANNAH_TESTER_SUBJECTS` | empty | Exact `sub` values, e.g. `auth0\|…`, `google-oauth2\|…`. |
| `HEROOS_HANNAH_MODEL` | `openai/gpt-oss-120b` | A model identifier (never a URL). |
| `GROQ_API_KEY` | unset | Secret. Unset: the demo answers 503 "Not configured". |

## Limits

- Message ≤ 2,000 characters; history ≤ 12 turns of ≤ 4,000 characters; the
  API sends the newest turns within 8,000 characters. Control characters and
  unknown fields are refused (422, field locations only).
- Provider request: temperature 0.3, `max_completion_tokens` 1024,
  `reasoning_effort: low`, reasoning not returned, 30 s timeout, no tools.
- 20 messages per tester per 5 minutes (in the API process), before the
  provider's own limits (HTTP 429 → "Too many requests" with `Retry-After`).
- Timeouts are ordered: provider 30 s < BFF→API 45 s < browser 55 s < route
  `maxDuration` 60 s. Page reads keep their 10 s timeout.

## Privacy and content

- The system instruction (`app/assistant/persona.py`) is generic and public.
  It contains no Playbook, Implementation Rules, Conditions Library or template
  content; no private knowledge pack is installed or sent to any provider.
- Nothing about the Case (title, subject, facts, answers) is sent: only what
  the user typed in the chat and the recent chat turns.
- Nothing logs a message, history, reply, prompt, key or identity subject; the
  API logs the outcome (`ok`, `rate_limited`, `timeout`, `unavailable`,
  `tester_limit`) and the number of turns. Responses are `no-store`.
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
