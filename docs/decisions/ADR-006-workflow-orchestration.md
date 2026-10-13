# ADR-006 — Workflow Domain vs Technical Orchestration

**Status:** Accepted  
**Date:** 2026-10-08  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline

## Context

HeroOS is fundamentally a workflow-driven HR platform.

The product must support long-running business processes such as:

- Disciplinary
- Probation
- Recruitment

These workflows involve:

- persistent cases
- workflow versions
- states
- transitions
- structured facts
- deterministic Conditions
- human decisions
- documents
- escalations
- audit history

Some implementation activities may also require technical orchestration such as:

- retries
- background jobs
- document generation
- asynchronous AI processing
- scheduled technical work
- long-running waits
- integration retries
- human wait/resume mechanics

These are related concerns, but they are not the same thing.

If AWS Step Functions becomes the source of truth for HeroOS HR workflow state,
the business model would become tightly coupled to AWS orchestration semantics.

If HeroOS implements all retry/timer/background mechanics directly in the
business workflow engine, unnecessary infrastructure complexity would leak
into the domain model.

The architecture therefore needs a strict boundary between:

1. HeroOS business workflow state
2. technical execution/orchestration

---

## Decision

HeroOS will own and persist HR workflow state inside the application domain and
PostgreSQL.

AWS Step Functions may be used for bounded technical orchestration where it
provides clear operational value.

Step Functions will **not** be the canonical source of truth for HeroOS case
or HR workflow state.

The fundamental rule is:

```text
HeroOS Workflow Engine
        =
business process truth

AWS Step Functions
        =
technical execution coordination
```
