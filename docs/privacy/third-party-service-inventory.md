# HeroOS V1 Third-Party Service Inventory

**Status:** Initial V1 inventory  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline  
**Last updated:** 2026-10-08

## 1. Purpose

This document identifies external services that are confirmed, proposed or
under consideration for HeroOS V1.

The inventory exists so HeroOS can understand:

- what external service is being used
- why it is required
- what categories of HeroOS data may reach it
- whether production customer/employee data is expected to reach it
- relevant region/residency considerations
- whether privacy/legal/vendor review is still required

This is a technical service inventory.

It does not by itself determine whether a vendor is legally classified as a
processor, subprocessor, controller or other legal role.

Formal privacy/legal classification must be confirmed separately where
required.

---

## 2. Status Definitions

### Confirmed

The service is already selected for the V1 architecture or project operation.

### Planned

The service is expected to be used, but final production configuration has
not yet been completed.

### Decision Required

The service category is required or likely required, but the final provider
or processing configuration has not yet been approved.

### Optional / Deferred

The service is not required for the current V1 baseline and will only be
introduced if a demonstrated need arises.

---

## 3. Production / Customer-Data Services

| Service | Status | Purpose | Potential Data | Production Customer Data Expected? | Region / Residency Consideration | Privacy / Legal Review |
|---|---|---|---|---|---|---|
| AWS | Confirmed | Primary HeroOS cloud infrastructure | Company, user, employee, case, workflow, document and operational data | Yes | Primary application infrastructure proposed in AWS Middle East (UAE), `me-central-1` | Required as production infrastructure provider |
| Amazon RDS for PostgreSQL | Confirmed | Authoritative application database | Company, membership, employee, case, workflow, facts, decisions, audit metadata | Yes | UAE region planned | Covered as part of AWS review |
| Amazon S3 | Confirmed | Private object/document storage | Uploaded and generated HR documents | Yes | UAE region planned where service configuration permits | Covered as part of AWS review |
| Amazon Cognito | Confirmed | Customer authentication | Account identity, email, authentication metadata | Yes | Production configuration must be reviewed for region and data-handling behavior | Covered as part of AWS review |
| AWS Secrets Manager | Confirmed | Production secret storage | Credentials and service secrets | No ordinary customer HR content expected | UAE-region infrastructure where applicable | Covered as part of AWS review |
| Amazon CloudWatch | Confirmed | Logs, metrics and operational monitoring | Minimized technical telemetry | Limited; sensitive HR content must not intentionally be logged | Logging region/retention must be configured deliberately | Covered as part of AWS review |
| AWS Step Functions | Planned | Bounded technical orchestration | Job identifiers and minimum required technical context | Potentially limited context only | UAE-region use planned when introduced | Covered as part of AWS review |
| Amazon SES | Planned / as required | Transactional email | Recipient identity, email address, controlled message content | Potentially | Region and email-content handling must be reviewed before sensitive use | Covered as part of AWS review |
| AI Provider | Decision Required | Language interpretation, structured extraction, controlled explanation and drafting | Minimum required customer/case context and approved HeroOS content | Potentially yes | Provider processing location, retention, training use and subprocessors must be reviewed before production-sensitive use | Explicit JJ/privacy/legal decision required |

---

## 4. Engineering and Project-Operations Services

The following services support development and project management.

They should not be used as general-purpose storage for production customer HR
data.

| Service | Status | Purpose | Intended Data | Customer HR Data Intended? | Notes |
|---|---|---|---|---|---|
| GitHub | Confirmed | Source control, pull requests and CI/CD integration | Source code, configuration templates, build metadata | No | Secrets and production customer data must not be committed |
| Linear | Confirmed | Project and engineering issue management | Product planning, technical issues, delivery metadata | No | Avoid placing real employee/case-sensitive information in issues |
| Slack | Confirmed | Team communication | Project discussions and coordination | No | Sensitive production HR data and credentials should not be shared in Slack |
| Ubuntu Development VPS | Confirmed development environment | Engineering workstation/runtime | Source code, synthetic development/test data | No production customer HR data intended | Development only; not Staging or Production |

---

## 5. Services Not Currently Selected

The following categories do not currently require an additional third-party
provider.

### Error Monitoring

Initial V1 baseline uses Amazon CloudWatch.

A third-party error-monitoring provider may be evaluated later if operational
need justifies:

- additional processor review
- privacy implications
- data minimization configuration
- additional cost

### External Vector Database

Not selected.

HeroOS does not currently require an external vector-database provider for V1.

If vector retrieval is required later, the preferred first evaluation should
consider PostgreSQL-compatible approaches before introducing another
production processor.

### External Workflow / BPM Platform

Not selected.

HeroOS owns its HR workflow domain.

AWS Step Functions may support technical orchestration, but no third-party BPM
system is authoritative for HeroOS business workflow state.

### External Authentication Provider

Not selected.

Amazon Cognito is the selected V1 authentication service.

### External File Storage Provider

Not selected.

Amazon S3 is the selected V1 private object-storage service.

---

## 6. AI Provider Decision Gate

The production AI provider remains intentionally unresolved.

Before production-sensitive HeroOS data is sent to an AI provider, the
following must be reviewed:

- provider/model
- task requirement
- minimum data required
- processing location
- storage location
- prompt/input retention
- output retention
- provider use of customer data for training
- available no-training / enterprise privacy controls
- subprocessors
- contractual terms / DPA availability
- deletion controls
- security capabilities
- UAE data-residency implications
- EU/GDPR-standard privacy implications
- expected operating cost

No AI provider should receive sensitive production HR data merely because an
API integration is technically available.

The final decision is tracked through the Privacy & Security Decision
Register.

---

## 7. Data-Minimization Requirements

External services should receive only information required for their defined
purpose.

Examples:

### CloudWatch

Prefer:

- request ID
- service
- status
- latency
- safe internal identifiers
- error category

Avoid:

- complete HR case narrative
- document contents
- passwords
- tokens
- full sensitive AI prompts

### AI Provider

Prefer:

- relevant workflow
- applicable structured facts
- minimum required user input
- approved HeroOS guidance needed for the task

Avoid:

- unrelated employee information
- complete company history
- unrelated documents
- authentication credentials
- unnecessary identifiers

### Email

Prefer:

- minimal notification content
- secure HeroOS link where appropriate

Avoid unnecessary sensitive case details in email.

---

## 8. Production Service Approval Rule

An external service may receive production-sensitive HeroOS data only when:

1. the technical purpose is defined
2. the data categories are understood
3. the minimum required data is identified
4. security controls are understood
5. relevant processing/residency implications are reviewed
6. material cost implications are understood
7. required JJ/product approval has been obtained
8. legal/privacy confirmation has been obtained where required

This process is:

```text
Technical Need
      |
      v
Provider Evaluation
      |
      v
Data / Privacy Review
      |
      v
Cost Review
      |
      v
Technical Recommendation
      |
      v
JJ / Legal Decision where required
      |
      v
Production Enablement