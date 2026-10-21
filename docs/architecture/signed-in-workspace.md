# Signed-in Workspace: Ask HeroOS, Company Blueprint, Company Space (M2-NEW-02)

**Status:** Implemented (M2-NEW-02). No API, schema or configuration change\
**Owner:** Technical Lead\
**Milestone:** [M2 — Reliable AI HR Workflow Platform](../milestones/m2-reliable-ai-hr-workflow-platform.md)\
**Visual source:** JJ's approved Oct 20 design package, frozen in
`apps/web/src/app/design-review/oct20/` (PR #52; gated by
`HEROOS_DESIGN_REVIEW=1`, fictional data)\
**Related:** [Customer Onboarding and Workspace UI](web-onboarding.md),
[Workflow Case Foundation](workflow-foundation.md),
[Hannah AI demo](hannah-ai-demo.md), [Security Boundaries](security-boundaries.md)

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
byte to `/branding/heroos-symbol.png` (`LogoSymbol`, `WorkspaceBrandMark` in
`components/site/brand-mark.tsx`). Every signed-in top bar uses it: the
workspace header and `AppShell` (loading, choosing a workspace, onboarding,
the sign-in states). The public site and the favicon keep the speech-bubble
logo.

Text fields inside a rounded control (the Ask composer, Search cases) show
focus on the control's rounded border (`focus-within`) and draw no outline of
their own. The global `:focus-visible` outline in `globals.css` is unlayered
CSS, so it outranks Tailwind utilities: such a field needs
`focus-visible:outline-hidden!` (the `!` is required) to turn it off.

## 2. Ask HeroOS and its seam

`components/ask/ask-workspace.tsx`: "What can HR do for you today?" and one
box. There is no workflow, category, stage or title to choose.

There is no AI behind it yet (M2-NEW-05/06). Sending goes through one seam,
`POST /bff/companies/{id}/ask` (`handleAskStart` in `lib/server/bff.ts`,
`lib/ask/model.ts`), which those issues repoint at the AI gateway. Today it:

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
the Blueprint the API keeps. Saves go through the existing
`PATCH /bff/companies/{id}/blueprint`:

- **Fields:** the company name (read-only), legal name, industry, number of
  employees, and the jurisdiction (DIFC / another, with its authority / not
  sure).
- **Jurisdiction display:** the confirmed name, or the founder's answer while
  unconfirmed. It is shown plainly with the API's readiness in its own words,
  never as a "confirmed" badge.
- **Editing:** read first; one "Edit Blueprint" for everything; a save bar
  only once something changed; "Edited" and "Updated" markers; a calm
  confirmation.
- **Completeness:** counts only the fields HeroOS keeps.
- **Who edits:** read-only for anyone the API doesn't let update it. The page
  carries no role or permission wording.

**Not stored by the API yet (M2-NEW-03), so not on the page:** the company
website, summary, policies, HR support, primary contact and people. The page
says these are coming next. No client-side storage stands in for them.

## 6. Company Space

`components/space/space-page.tsx`: a reference page, not a dashboard.
It shows the company's identity, the account's access from its role (what it
can use, in words), the Blueprint's completeness and who is signed in.

There are no plans, prices, limits, quotas, analytics or case lists. HeroOS
has no entitlements yet (M2-NEW-10). Expert Review is shown as "To be
confirmed". The API offers no list of a Company's people, so the page says it
can't list them yet.

## 7. Differences from the frozen mockups

| Difference | Why |
| --- | --- |
| No first name ("Welcome." / "Welcome back.") and a neutral avatar | The web app has no user name or email (the session holds an access token only) |
| No visible "Stop · HeroOS can't proceed" label on a block (stop sign + panel; "Stop" for screen readers) | JJ, 21 Oct |
| "Edit Blueprint" is yellow; "Number of employees" | JJ, 21 Oct |
| Blueprint without summary, policies, HR support or people; Space without plan names and other people | Not in the API (M2-NEW-03, M2-NEW-10); nothing is invented |
| No free-text reply box on a case; no quick-reply chips | Nothing can answer free text until the AI conversation (M2-NEW-05/06); the question groups are the reply. Chips weren't approved by JJ |
| Account menu without "Account settings" | No such page exists |
| A one-line environment notice at the foot of each page | Synthetic-data demonstration environment |
| Header with a light background when the page scrolls; documents, decisions and next steps as quiet sections under the conversation | Pages scroll as documents (not inner panes); the official record stays on the case page |
| Some small links and chips are 44 px tall on phones | The repository's touch-target rule (e2e A11Y-2) |

## 8. Hannah

There is no Hannah in the three pages, following the frozen mockups. Her chat
tab was removed from the case page; the demo's API and BFF remain
([Hannah AI demo](hannah-ai-demo.md)).

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
