# ADR-005 — Private Document and Object Storage

**Status:** Accepted  
**Date:** 2026-10-08  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline

## Context

HeroOS V1 will handle sensitive HR-related files and generated documents.

Examples include:

- uploaded supporting documents
- employee/case-related files
- generated letters
- generated checklists
- controlled document outputs
- future workflow attachments

These objects may contain personal, employment or case-sensitive information.

Document security must follow the same tenant-isolation model as the rest of
HeroOS.

Knowing an object identifier or storage path must never be sufficient to gain
access.

The solution must support:

- private-by-default storage
- tenant ownership
- authenticated access
- authorization before retrieval
- controlled temporary download/access
- secure uploads
- auditability
- environment separation
- encryption
- future document lifecycle rules
- compatibility with generated documents

---

## Decision

HeroOS V1 will use **Amazon S3** for private document and object storage.

PostgreSQL remains authoritative for document metadata, tenant ownership and
business relationships.

S3 stores object bytes.

The core model is:

```text
PostgreSQL
-----------
Document ID
Company ID
Case ID
Document Type
Storage Key
Status
Metadata
Created By
Created At

        |
        v

Private Amazon S3
-----------------
Actual object bytes