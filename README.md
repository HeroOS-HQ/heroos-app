# HeroOS

HeroOS is a guided HR workflow platform that combines structured workflows,
deterministic Conditions, approved HR guidance and controlled AI assistance.

## V1 Scope

Initial workflows:

- Disciplinary
- Probation
- Recruitment

Initial jurisdictions:

- UAE Federal / MOHRE
- DIFC

ADGM is outside the V1 scope.

## Technology

- Next.js / TypeScript
- FastAPI / Python 3.12
- PostgreSQL
- AWS
- pnpm
- uv

## Repository Structure

```text
apps/
  web/        Next.js frontend
  api/        FastAPI backend

docs/
  architecture/
  decisions/
  privacy/

infrastructure/
  terraform/

.github/
  workflows/