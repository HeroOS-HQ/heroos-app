# Signed-in Workspace: Ask HeroOS, Company Blueprint, Company Space (M2-NEW-02)

**Status:** Implemented (M2-NEW-02; the Company Blueprint completed by M2-NEW-03, see
[Company Blueprint](company-blueprint.md))\
**Owner:** Technical Lead\
**Milestone:** [M2 — Reliable AI HR Workflow Platform](../milestones/m2-reliable-ai-hr-workflow-platform.md)\
**Visual source:** JJ's approved Oct 20 design package, frozen in
`apps/web/src/app/design-review/oct20/` (PR #52; gated by
`HEROOS_DESIGN_REVIEW=1`, fictional data)\
**Related:** [Customer Onboarding and Workspace UI](web-onboarding.md),
[Workflow Case Foundation](workflow-foundation.md),
[Hannah AI demo](hannah-ai-demo.md), [Security Boundaries](security-boundaries.md)

> **Current architecture (M2-NEW-08):** Ask HeroOS reads the Case's workflow position, the Case is chat-first (its formal steps appear inline in the conversation) and requested decisions can need the Case's formal record. See [disciplinary-reference-workflow.md](disciplinary-reference-workflow.md). This document stays the record of what its own milestone built.

## 1. What it is

The signed-in product is three areas, one quiet header, and no permanent
navigation:

| Area | Route | Notes |
| --- | --- | --- |
| **Ask HeroOS** (the home) | `/workspaces/{id}` | One question in the founder's own words; `?cases=open` opens the Cases drawer |
| A case | `/workspaces/{id}/cases/{caseId}` | The case's conversation, what HeroOS needs to know, then the official record (next steps, decisions & history, documents) |
| **Company Blueprint** | `/workspaces/{id}/settings` | The URL keeps its earlier name so saved links work |
| **Company Space** | `/workspaces/{id}/space` | New |

Retired pages redirect so saved links still land somewhere useful:

| Old route | Now |
| --- | --- |
| `/hr-services`, `/cases/new` | Ask HeroOS |
| `/cases` (list), `/disciplinary` (overview) | Ask HeroOS with the Cases drawer open |

The header has HeroOS's mark (back to Ask HeroOS) and **Cases** on the left,
the open case's name and status in the centre on a case page, and the
**account menu** on the right: Company Blueprint, Company Space, another
workspace (when the account has several) and sign out. The Dashboard,
HR Services and "Team & Access" navigation are gone; the components that only
served them were removed.

The production code never imports the design-review package
(`security-boundaries.test.ts`). The approved logo symbol is copied byte for
byte to `/branding/heroos-symbol.png` (`LogoSymbol`, `BrandMark` in
`components/site/brand-mark.tsx`). It is the one logo everywhere: the public
site's header and footer, the workspace header and `AppShell` (loading,
choosing a workspace, onboarding, the sign-in states). Only the favicon and
app icons still carry the earlier speech-bubble symbol (separate files), and
the frozen design-review package keeps its own copy.

Text fields inside a rounded control (the Ask composer, Search cases) show
focus on the control's rounded border (`focus-within`) and draw no outline of
their own. The global `:focus-visible` outline in `globals.css` is unlayered
CSS, so it outranks Tailwind utilities: such a field needs
`focus-visible:outline-hidden!` (the `!` is required) to turn it off.

## 2. Ask HeroOS and its seam

`components/ask/ask-workspace.tsx`: "What can HR do for you today?" and one
box. There is no workflow, category, stage or title to choose.

It answers in one of two ways, decided by the API (`GET
/companies/{id}/assistant`, read server-side by `loadAskGateway`):

- **The AI conversation (M2-NEW-05)**, when Ask HeroOS's controlled gateway
  can answer for this administrator: Send starts a conversation with HeroOS
  through `POST /bff/companies/{id}/assistant/messages`
  (`ask-conversation.tsx`, `lib/ask/conversation.ts`). No case is opened;
  HeroOS answers from the approved knowledge runtime only and its turns carry
  no outcome label or colour. See [ai-gateway.md](ai-gateway.md).
- **Otherwise** (the gateway is off by default, or not configured, or has no
  approved knowledge, or the API predates it): sending goes through the Ask
  seam, `POST /bff/companies/{id}/ask` (`handleAskStart` in
  `lib/server/bff.ts`, `lib/ask/model.ts`). M2-NEW-06/07 connect the
  conversation to cases. Today the seam:

1. opens a case of the reference workflow (Disciplinary, the only one HeroOS
   runs) through the existing API, with a neutral title made in the founder's
   time zone (`New case · 21 Oct, 09:12`; never the founder's words, which may
   name an employee);
2. reads the case for its revision;
3. saves the founder's words, exactly as written, as the first answer
   (`initial_facts` / `incident.narrative`, at most 4,000 characters).

| Property | How |
| --- | --- |
| Request | `{text, title, requestKey, submissionKey}`; CSRF, JSON-only, size and session checked by the shared BFF guard; rebuilt field by field (`parseAskStart`: the API's free-text rules, unknown fields refused) |
| One case per question | `requestKey` (create) and `submissionKey` (save): a retry of the same words reuses both, so the API applies each write once. A double click sends once |
| Answer | `200 {caseId, narrativeSaved}`. A case that opened but couldn't take the words (a lost save, a changed definition) is still a case: the page says so, links to it and keeps the words in the box |
| Who | Administrators (the API enforces it). Members see the box disabled, with the reason in words |

The case then follows HeroOS's guided Disciplinary workflow. Its conversation
says it isn't AI, and it is not presented as AI anywhere.

## 3. Outcomes in the conversation

`components/ask/response-tone.tsx` defines the four outcomes of a HeroOS turn
with JJ's colours, always with words and an icon:

| Outcome | Colour | Today, from the deterministic workflow (`components/cases/conversation.tsx`) |
| --- | --- | --- |
| Guidance | blue | information, question groups, missing information, info notices |
| Warning | amber | intake cautions; caution notices |
| Block | red | a hold until the jurisdiction is confirmed |
| Expert Review | dark pink | a hold for specialist review (no request button: there is no Expert Review flow yet) |

The outcome is never decided in the web app. M2-NEW-06 passes the outcome the
Conditions engine decided for an AI turn into the same `AdviserTurn`.

## 4. Cases and case status

- **Cases drawer** (`components/app/cases-panel.tsx`): the Company's cases as
  the API lists them (title, status in words, last update), today's first.
  It includes a local search and New question. Administrators only, like
  cases.
- **Case status** (`components/cases/case-status-panel.tsx`): opened from the
  case's name in the header; a bottom sheet on phones. All of it is the API's
  view of the case:
  - the status and the stage in progress;
  - the hold and cautions (never folded away), and a recorded need for
    specialist review, which the header shows too;
  - the next official step;
  - what's done and still needed;
  - the facts given;
  - the latest history;
  - how HeroOS tailored the case, and the full case details, folded away.

## 5. Company Blueprint

`components/blueprint/blueprint-page.tsx` and `lib/blueprint/model.ts` work on
the Blueprint the API keeps, the canonical company context
([Company Blueprint](company-blueprint.md)). Saves go through
`PATCH /bff/companies/{id}/blueprint`:

- **Sections:** Company basics (the company name, read-only; legal name,
  industry, number of employees, website, company summary), Jurisdiction
  (DIFC / another, with its authority / not sure), Policies (do HR policies
  exist, policy details; document upload isn't available), HR support (how HR
  is handled, notes) and People (the primary contact, who is signed in, who
  else has access: by "You" and joining date, since HeroOS keeps no names).
- **Jurisdiction display:** the confirmed name, or the founder's answer while
  unconfirmed. It is shown plainly with the API's readiness in its own words,
  never as a "confirmed" badge.
- **Editing:** read first; one "Edit Blueprint" for everything; a save bar
  only once something changed; "Edited" and "Updated" markers; a calm
  confirmation.
- **Completeness:** the API's (`completeness.missing`); website and notes
  never need attention.
- **Last updated:** the row's update time, with the time of day (UTC).
- **Who edits:** read-only for anyone the API doesn't let update it. The page
  carries no role or permission wording.

Against an API without the company context (before migration D5 and the
M2-NEW-03 API are deployed) the page reads the Blueprint as `legacy`: it shows
and saves only the profile and jurisdiction and says the rest is coming next.

## 6. Company Space

`components/space/space-page.tsx`: a reference page, not a dashboard.
It shows the company's identity, the account's access from its role (what it
can use, in words), the Blueprint's completeness (the API's, so it reflects
the full company context) and last update, who is signed in and how many
other people have access (no names: HeroOS keeps none).

There are no plans, prices, limits, quotas, analytics or case lists. HeroOS
has no entitlements yet (M2-NEW-10). Expert Review is shown as "To be
confirmed". People's names and access management are M2-NEW-10.

## 7. Differences from the frozen mockups

| Difference | Why |
| --- | --- |
| No first name ("Welcome." / "Welcome back.") and a neutral avatar | The web app has no user name or email (the session holds an access token only) |
| No visible "Stop · HeroOS can't proceed" label on a block (stop sign + panel; "Stop" for screen readers) | JJ, 21 Oct |
| "Edit Blueprint" is yellow; "Number of employees" | JJ, 21 Oct |
| Blueprint people without names, emails, avatars or job titles; no policy documents; Space without plan names | HeroOS keeps no names or emails (M2-NEW-10); document retention is undecided (PRIV-004); nothing is invented |
| No free-text reply box on a case; no quick-reply chips | Nothing can answer free text until the AI conversation (M2-NEW-05/06); the question groups are the reply. Chips weren't approved by JJ |
| Account menu without "Account settings" | No such page exists |
| A one-line environment notice at the foot of each page | Synthetic-data demonstration environment |
| Header with a light background when the page scrolls; documents, decisions and next steps as quiet sections under the conversation | Pages scroll as documents (not inner panes); the official record stays on the case page |
| Some small links and chips are 44 px tall on phones | The repository's touch-target rule (e2e A11Y-2) |

## 8. Hannah

There is no Hannah in the three pages, following the frozen mockups. JJ
(21 Oct) would like her back, small, on the Blueprint and Company Space (for
example taking notes); that needs an approved pose asset first, and no new art
or animation is added meanwhile. Her chat tab was removed from the case page;
the demo's API and BFF remain ([Hannah AI demo](hannah-ai-demo.md)).

## 9. Tests

- **Web unit tests:**
  - `components/app/workspace-header.test.tsx` (the three destinations and no
    dashboard, the account menu, the Cases control and drawer);
  - `components/ask/ask-workspace.test.tsx`;
  - `components/blueprint/blueprint-page.test.tsx`;
  - `components/space/space-page.test.tsx`;
  - `components/cases/cases.test.tsx` (thread outcomes, case status, no Hannah);
  - `lib/server/ask-bff.test.ts`;
  - `security-boundaries.test.ts` (client files, the Ask route through the
    shared guard, no design-review imports).
- **End to end (`make e2e-check`):**
  - `cases` (Ask opens one case with the words saved; the drawer; a member's
    disabled box);
  - `journey` (the founder demo starts on Ask HeroOS);
  - `browser` (Blueprint editing, a demoted administrator, switching
    workspaces, the account menu by keyboard, responsive layout of the three
    pages).

## 10. M2-NEW-08: the chat-first Case

- **Ask HeroOS is the Case's conversation.** A conversation with a Case shows the Case's position under its title (the pathway "(your decision)", the stage in progress or next) and its next formal step inline (`components/ask/case-steps.tsx`), one at a time:
  - the employee's jurisdiction and the safety screening (never collected by the AI);
  - the pathway choice;
  - a stage checklist question;
  - start or complete, with "I understand" for a caution;
  - a refusal in the API's words.

  Each button calls the Case's existing route and only the founder's click takes it.
- **The Case page is the record and review surface.** In order:
  1. "Continue with HeroOS";
  2. the case notices (hold, cautions, jurisdiction);
  3. "Case details" folded until "Review case details";
  4. Next steps, Decisions & history, Documents.

  The guided conversation thread, and its "not an AI assistant" welcome, isn't shown.
- **A greeting** ("Hi Hannah") is answered as one and never opens a Case, with or without the AI gateway.
