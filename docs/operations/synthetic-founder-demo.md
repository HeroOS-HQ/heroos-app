# Synthetic Disciplinary Journey and Founder Demo (M2-05)

**Status:** Local and CI only. Never on shared staging or production.\
**Owner:** Technical Lead\
**Related:** [Local End-to-End Validation](local-end-to-end-validation.md),
[Workflow Progression](../architecture/workflow-progression.md),
[Employer Decisions and History](../architecture/workflow-decisions.md),
[Document Templates and Safe Previews](../architecture/document-templates.md)

## 1. What it is

One complete Disciplinary case, in the order an employer meets the M2 features, through the real product. That means the real browser, web BFF, API, PostgreSQL with RLS and the runtime role, the workflow engine, decision records, the unified history, template eligibility and previews. Nothing is mocked or skipped:

1. **Start:** the administrator signs in and chooses the company (they belong to two).
2. **Ask HeroOS:** they explain the situation in their own words on Ask HeroOS, the signed-in home. That opens a case (M2-NEW-02) with their words saved as its first answer. The conversation says it is a guided workflow, not AI.
3. **Intake:** the intake collects the facts. A follow-up appears only when an answer needs it.
4. **Jurisdiction:** it is confirmed for the case against the company's operator-confirmed jurisdiction.
5. **Screening:** a clear safety screening records the intake as a *preliminary* status, not a legal assessment.
6. **Pathway:** HeroOS suggests no pathway. The employer chooses one, and acknowledges the caution that choice raises.
7. **Stage 1:** it can't be completed until its checklist is met, and the screen says what's missing.
8. **First template:** stage 1's template can be previewed. The preview is watermarked, has visible gaps, and offers nothing to issue, send or download.
9. **Employer record:** the employer records a factual decision. The workflow doesn't move.
10. **Second template:** at stage 2, its template waits, in sight and with its reason, until its precondition is answered. Then it can be previewed.
11. **Completion caution:** completing stage 2 raises a caution that must be acknowledged first.
12. **Hold:** at stage 3, an answer that needs outside help puts the case on hold for specialist review. Completion is refused and no document can be previewed.
13. **History:** the unified history shows every step, in order.
14. **Persistence:** a reload and a new sign-in keep everything. The page fits a 390 px phone.
15. **Refusals** (real API and database):
    - completing a held stage is refused;
    - a record claiming the hold is cleared changes nothing;
    - a member gets 403 and another company gets 404;
    - no document, preview, penalty or sanction table exists;
    - the previewed name was never stored.

## 2. Everything in it is fictional

| Item | Value |
| --- | --- |
| Companies, people | `[SYNTHETIC DEMO] Example Trading LLC`, `Sam Example (fictional)` |
| Rules | The synthetic rule bundle (`apps/api/tests/fixtures/rule_bundles/`), announced on screen as "Synthetic test rules". Its stages ("Test stage 1: Check-in conversation", …) are invented to exercise the engine |
| Templates | The synthetic template bundle (`apps/api/tests/fixtures/template_bundles/`), announced as "Synthetic test templates" and "provisional, not approved for use". Bound by exact version to the synthetic rules |
| Database | A disposable PostgreSQL container created for the run and deleted after it. No shared credentials |

**These rules are not JJ's methodology and not UAE legal guidance.** JJ's
real stages, conditions and letters arrive as private bundles only after
her content decisions, the lawyer's approval and a release authorization.
Production refuses synthetic bundles.

## 3. Running it

**Prerequisites:** the same as for the end-to-end suite ([§3 there](local-end-to-end-validation.md#3-running-it)):
- Docker, with the `postgres:16-alpine` image;
- `uv`, `pnpm` and Node.js 22, with dependencies installed once (`pnpm install --frozen-lockfile` and `cd apps/api && uv sync --frozen`);
- Google Chrome (or `E2E_CHROME`);
- the local ports 55440–55447 free.

For the visible window, a graphical session (`DISPLAY` or `WAYLAND_DISPLAY`). Without one, `E2E_DEMO_HEADLESS=1` keeps the browser hidden.

**Isolation.** It needs no credentials, `.env` file or access to any shared environment, and it never reads them:
- every process runs in a cleared environment;
- the database is a throwaway container on 127.0.0.1 and 127.0.0.2;
- sign-in is a local test provider, with throwaway TLS;
- the developer database volume (`heroos-local`) is checked untouched.

```
E2E_SUITES=journey make e2e-check   # automated: 17 checks (JOURNEY-0…16) and screenshots
make demo-synthetic                  # live: the journey in a visible browser, then the environment stays up
```

**What `make demo-synthetic` does:**
- It plays the journey in a visible Chrome window that trusts only this run's certificate authority.
- It then leaves that window signed in as the fictional administrator on the finished case.
- It prints the URL and the subject to type on the test sign-in page.
- It stops on Ctrl-C, or after `E2E_DEMO_MINUTES` (default 60), and deletes everything.

**During the hold**, the presenter can start a new case by hand to show any other path: a held screening, a "Not sure" answer, another pathway.

Screenshots of the automated run are in `e2e/.output/<timestamp>/screenshots/journey-NN-*.png`. They make up the storyboard of the founder demo script.

## 4. What it proves, and what it doesn't

It proves that the M2 features work together, end to end, under the real security model. It **doesn't** validate any disciplinary content. On shared staging no rule or template bundle is installed, so there:
- next steps say progression isn't available;
- Documents say templates aren't available;
- the intake can't be completed while the sensitive screening is disabled.

That is the intended fail-closed state until approvals exist.
