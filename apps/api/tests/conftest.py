"""Test-run configuration, applied before any application module is imported.

HEROOS_ENV is required with no default. The suite runs against an explicit
development configuration, independent of the developer's shell.

There is no built-in DATABASE_URL either (docs/operations/database-credentials.md).
Unit tests get an unresolvable placeholder, so nothing can reach a real database
or depend on a developer's credentials. The real-PostgreSQL suites build their
own URLs from TENANT_TEST_* / RECOVERY_TEST_* configuration.
"""

import os

for _name in [name for name in os.environ if name.startswith("HEROOS_")]:
    del os.environ[_name]
os.environ.pop("MIGRATION_DATABASE_URL", None)
os.environ["HEROOS_ENV"] = "development"
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://heroos_app:unit-test-placeholder@db.invalid/heroos"
)
