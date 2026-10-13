# HeroOS Production Security Gates (M5 Activation Contract)

**Status:** Requirements defined (M1-07). **None of these production controls is active.** No AWS resource has been created\
**Owner:** Technical Lead\
**Milestone:** M1 — Foundation & Security (definition); M5 (activation; moved from M3 on 2026-10-09, see [Delivery Plan](../milestones/delivery-plan.md))\
**Issue:** M1-07 — Establish secure storage, secrets, logging & backup foundation\
**Related:** [ADR-002](../decisions/ADR-002-aws-infrastructure.md),
[Private Object Storage](private-object-storage.md), [Observability](observability.md),
[Backup and Recovery](backup-and-recovery.md), [Decision Register](../privacy/decision-register.md)

HeroOS is **local-first, cloud-ready, cloud-late**. M1 defines the application
contracts and proves them locally and in CI, and M2 to M4 build the product
locally and in CI on top of them. M5 provisions AWS (`me-central-1`, ADR-002),
deploys Staging and runs cloud test/fix/redeploy loops, and must satisfy every
gate below before production customer data is accepted. Each gate is a release blocker for production, not a
recommendation.

## 1. What M1 proves locally vs. what M5 must activate

| Area | Locally proven in M1 | Deferred to M5 |
| --- | --- | --- |
| Object storage | provider contract, Company-namespaced server-generated keys, write-once, containment, private local provider, fail-closed config, `s3` refused until implemented | S3 adapter, private bucket, Block Public Access, encryption, IAM, pre-signed access |
| Database | RLS, non-bypass runtime role, startup guard, logical backup/restore with post-restore security validation | RDS, encryption at rest, TLS enforcement, automated backups, PITR, restore drills |
| Secrets | `SecretStr` config, no secret rendering, no built-in database credentials in any environment (generated, untracked `.env` locally; [Database Credentials](../operations/database-credentials.md)), deployed environments refuse local database hosts and the migration credential, no committed credentials (CI scans for them) | AWS Secrets Manager, IAM-scoped retrieval, rotation |
| Ingress | none | ACM certificate, ALB HTTPS, HTTP → HTTPS redirect |
| Logging | structured JSON stdout, request correlation, sanitized errors, no access log, leakage tests | CloudWatch ingestion, retention, metric filters |
| Monitoring | 5xx and unhandled errors are distinguishable events | alarms, dashboards, backup-failure notifications |

## 2. Object storage: S3

- Private bucket per environment. **S3 Block Public Access** on at the account
  and bucket level. Object Ownership "bucket owner enforced" (no ACLs). No public
  bucket policy.
- **Encryption at rest** (SSE-S3 or SSE-KMS; key ownership decided at M5).
- **HTTPS only**: the bucket policy denies requests without
  `aws:SecureTransport`.
- **Scoped IAM**: the API task role may only get, put and delete
  `companies/*` objects. No bucket administration and no wildcard `s3:*`.
- Keys are exactly `companies/<company uuid>/<object uuid>`, built by
  `PrivateObjectService` from `CompanyScope`.
- **Pre-signed URLs only after HeroOS authorization**: authentication →
  Membership → object scope validation → short-lived pre-signed URL for one key.
  Possession of a key, path or URL pattern is never authorization.
- Versioning, lifecycle and replication follow PRIV-004 and PRIV-019 once
  approved.
- Details: [Private Object Storage §6](private-object-storage.md#6-production-s3-contract-m5).

## 3. Database: RDS for PostgreSQL

- PostgreSQL 16, private subnets, no public accessibility.
- **Encryption at rest** (KMS), enabled at creation.
- **TLS in transit**: `rds.force_ssl = 1`, and clients use `sslmode=verify-full`
  with the RDS CA bundle in `DATABASE_URL` / `MIGRATION_DATABASE_URL`.
- **Automated backups** and **PITR** enabled. The retention window follows
  PRIV-007, and RPO/RTO follow PRIV-017.
- **Restore procedure**: [Backup and Recovery](backup-and-recovery.md),
  including the role bootstrap order and post-restore validation. Restore drills
  are scheduled.
- **Non-bypass application role**: the API login role is a member of
  `heroos_app_runtime`, not superuser, no `BYPASSRLS`/`CREATEROLE`, and owns no
  tables. The API startup guard enforces this. Grants and ownership are
  re-reviewed on RDS, where the master user is not a superuser.
- **Separate migration/admin capability**: migrations run as a dedicated
  migration task with the admin credential. The API task never receives
  `MIGRATION_DATABASE_URL`; the API refuses to start if it does.

## 4. Secrets

- Production secrets live outside source control in **AWS Secrets Manager** (or
  another explicitly approved store), injected into ECS tasks as environment
  variables or secrets. Never baked into images: `.env` is excluded by
  `.dockerignore`, and the API image copies only dependency manifests and
  `apps/api/app`.
- **Least privilege**: each task role can read only its own secrets. The API
  task cannot read the migration credential or any identity-operator credential
  (ADR-008); the API refuses to start with either, and operator logins are
  per-person and never stored with a service.
- **Rotation** for database credentials where RDS integration supports it. The
  strategy is chosen at M5.
- No plaintext secret logging: configuration secrets are `SecretStr`, validation
  errors hide inputs, and the log formatter emits only allowlisted fields.
- Deployed environments fail closed: `HEROOS_DEV_AUTH_SECRET` must be absent,
  `HEROOS_AUTH_PROVIDER` must be `cognito`, `DATABASE_URL` must be set
  explicitly and must not be the local development default, and
  `HEROOS_STORAGE_PROVIDER=local` / `HEROOS_LOCAL_STORAGE_ROOT` are refused.

## 5. Ingress

- **HTTPS/TLS** terminated at the ALB with an **ACM** certificate. Modern TLS
  policy (TLS 1.2+).
- **HTTP → HTTPS redirect** on the ALB listener.
- ECS tasks are reachable only from the ALB security group.
- The Uvicorn access log stays off. Request logging is the application's
  `request_completed` event.

## 6. Logging

- Applications write JSON lines to stdout/stderr, collected by the ECS awslogs
  driver (or FireLens) into **CloudWatch Logs**.
- **Retention**: pending PRIV-006. Until it is approved, retention must be
  explicitly configured, never "never expire" by default.
- No HR content in logs: [Observability §2](observability.md#2-log-format). The
  M1 leakage tests are part of CI.
- Any third-party log or error service needs a service-inventory entry and
  privacy review before activation.

## 7. Monitoring

- Application 5xx visibility: a metric filter or alarm on
  `"event":"unhandled_exception"` and on 5xx `request_completed`.
- Health and deployment visibility: ALB target health, ECS deployment circuit
  breaker and events.
- Backup failure visibility: RDS backup and snapshot event notifications.
- Infrastructure alarms (CPU, memory, storage, connections) are chosen during
  M5.

## 8. Decisions that gate activation

These register decisions are pending. M5 must not answer them with a default
configuration. See the
[traceability matrix](../privacy/decision-register.md#decision-to-implementation-traceability).

| Decision | Blocks |
| --- | --- |
| PRIV-006 log retention | CloudWatch log-group retention (§6) |
| PRIV-007 backup retention, PRIV-017 RPO/RTO | RDS backup/PITR configuration and restore-drill criteria (§3) |
| PRIV-013 residency | Region choices for Cognito, SES, monitoring and any cross-region copy |
| PRIV-014 vendor approval | Any vendor receiving production customer data |
| PRIV-019 object versioning | S3 versioning and lifecycle (§2) |
| PRIV-009 to PRIV-012, PRIV-021 | Any external AI provider receiving identifiable or customer data. This can arise in M4 (Intelligence Layer), before cloud activation |

## 9. Explicitly not done in M1

No AWS account access, Terraform apply, S3 bucket, Secrets Manager secret,
CloudWatch log group, RDS instance, KMS key, ACM certificate, ALB or backup
policy was created or contacted in M1-07. Application tests never contact AWS.
