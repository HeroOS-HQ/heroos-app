# HeroOS V1 Sensitive Data Flow

**Status:** Draft architecture baseline  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline  
**Last updated:** 2026-10-08

## 1. Purpose

This document describes how customer, employee, HR case, authentication,
document and AI-processing data moves through HeroOS V1.

Its purpose is to make trust boundaries explicit before implementation and
to identify where authorization, encryption, privacy controls, audit
recording and product/legal decisions are required.

This document describes intended V1 architecture.

It does not define legal retention periods or independently determine
privacy compliance.

---

## 2. Data Categories

HeroOS V1 may process several categories of information.

### 2.1 Account and Identity Data

Examples:

- user name
- email address
- authentication identifiers
- company membership
- login/session metadata
- authorization context

Primary systems:

- Amazon Cognito
- HeroOS application database

### 2.2 Company Data

Examples:

- company name
- jurisdiction
- Company Blueprint information
- company configuration
- membership information

Primary system:

- PostgreSQL

### 2.3 Employee / Case Subject Data

Examples:

- employee name
- employment-related identifiers
- role/job information
- employment dates
- case-related employment facts

Primary system:

- PostgreSQL

This information may contain personal information and must be treated as
tenant-private data.

### 2.4 HR Case Data

Examples:

- customer-described HR situation
- structured facts
- workflow state
- jurisdiction
- Condition evaluations
- human decisions
- escalation state
- case notes

Primary system:

- PostgreSQL

HR case information may be sensitive and must not be exposed across tenant
boundaries or unnecessarily copied into operational systems.

### 2.5 Documents

Examples:

- generated letters
- supporting HR documents
- uploaded case files
- controlled templates
- generated checklists

Primary storage:

- private Amazon S3 objects

Document metadata remains in PostgreSQL.

### 2.6 Approved HR Knowledge

Examples:

- Playbooks
- approved Conditions
- approved references
- controlled templates
- effective/version metadata

Primary system:

- PostgreSQL and/or controlled application-managed knowledge storage

Only approved active content may influence production guidance.

### 2.7 AI Processing Data

AI requests may contain only the information required for the specific AI
task.

Possible content includes:

- user-entered situation text
- selected structured case facts
- relevant workflow context
- approved HeroOS guidance
- required response schema

AI provider processing and retention rules are subject to separate provider,
privacy and product decisions.
They are tracked in the
[decision register](../privacy/decision-register.md): provider (PRIV-009),
retention (PRIV-010), training use (PRIV-011), location (PRIV-012) and which
data categories may be sent (PRIV-021).

---

## 3. Primary Trust Boundaries

HeroOS has the following important trust boundaries.

```text
Customer Browser
      |
      | HTTPS
      v
HeroOS Public Application Boundary
      |
      v
Authenticated Backend Boundary
      |
      +----------------------+
      |                      |
      v                      v
HeroOS Private Data      Approved External
Boundary                 Service Boundary
      |                      |
      |                      +--> AI Provider
      |                      +--> Email Provider
      |
      +--> PostgreSQL
      +--> Private S3
      +--> Secrets Manager
      +--> Technical Orchestration
```
