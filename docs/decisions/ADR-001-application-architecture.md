# ADR-001 — HeroOS V1 Application Architecture

**Status:** Accepted  
**Date:** 2026-10-08  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline

## Context

HeroOS V1 must deliver three production workflows:

- Disciplinary
- Probation
- Recruitment

These workflows must run on a reusable platform rather than as three separately
hard-coded applications.

The product must also provide:

- strong tenant isolation
- persistent cases and workflow state
- deterministic Conditions
- approved HR knowledge
- controlled AI assistance
- private document handling
- auditability
- safe escalation
- production deployment within the V1 delivery window

The system needs clear domain boundaries without introducing unnecessary
distributed-system complexity during the initial release.

---

## Decision

HeroOS V1 will use a **modular monolith** architecture.

The primary application components will be:

- Next.js web application
- FastAPI backend application
- PostgreSQL authoritative application database
- private object storage
- managed authentication
- controlled AI Gateway
- optional AWS technical orchestration where justified

The backend will initially be deployed as one application while maintaining
strong logical separation between domain modules.

---

## Application Boundary

The high-level application flow is:

```text
Customer / Admin
       |
       v
Next.js Web Application
       |
       v
FastAPI Application API
       |
       v
Application / Domain Services
       |
       +-----------------------------+
       |             |               |
       v             v               v
   PostgreSQL    Private S3      External Services
                                  via controlled
                                  application gateways