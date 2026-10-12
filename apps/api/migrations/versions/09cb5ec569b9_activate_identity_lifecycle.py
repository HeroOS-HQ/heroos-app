"""activate identity lifecycle and operator provisioning (B1b)

M1-10B, ADR-008. Run only after the new API (which never reads
``users.identity_subject``) is deployed on B1a (``b8a11c15ed91``).

- Verifies that every User has exactly one active binding whose subject equals
  its legacy ``identity_subject``. Drift (e.g. a User added outside the
  migration path) is refused, never repaired silently.
- Drops ``users.identity_subject``. The previous API (``371dd50``) maps that
  column, so from here on it fails closed on every protected request instead of
  ignoring lifecycle state.
- Grants ``heroos_identity_operator`` the minimum privileges to provision,
  bind, suspend, revoke and reactivate: column-level UPDATE (bindings stay
  immutable), no DELETE, Company id lookup only, nothing on HR tables. Its
  Membership writes stay under the tenant_isolation policy.
- ``heroos_schema_contract()`` = 2.

Only now can lifecycle changes exist, so no lifecycle state ever coexists with a
schema the previous API could use.

Downgrade refuses once any identity or Membership change has been audited since
the B1a backfill, whatever the current status values are: roll forward instead.

Revision ID: 09cb5ec569b9
Revises: b8a11c15ed91
Create Date: 2026-10-12 15:30:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "09cb5ec569b9"
down_revision: str | Sequence[str] | None = "b8a11c15ed91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPERATOR_ROLE = "heroos_identity_operator"
B1A_BACKFILL_REFERENCE = "alembic:b8a11c15ed91"

# (table, privileges, column-scoped UPDATE)
OPERATOR_GRANTS = (
    ("users", "SELECT, INSERT", "status, suspended_at, updated_at"),
    ("user_identities", "SELECT, INSERT", "status, revoked_at, updated_at"),
    ("memberships", "SELECT, INSERT", "status, revoked_at, updated_at"),
)


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true.

    Runs on the server, so it also holds in rendered ``--sql`` scripts.
    """
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def _lock() -> None:
    op.execute(
        "LOCK TABLE users, user_identities, memberships, identity_events, membership_events "
        "IN ACCESS EXCLUSIVE MODE"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _lock()
    guard(
        """EXISTS (
            SELECT FROM users u
            WHERE (SELECT count(*) FROM user_identities i WHERE i.user_id = u.id) <> 1
               OR NOT EXISTS (
                    SELECT FROM user_identities i
                    WHERE i.user_id = u.id AND i.status = 'active'
                      AND i.subject = u.identity_subject))""",
        "some users lack exactly one active binding matching their legacy identity_subject; "
        "reconcile them before B1b",
    )

    op.drop_constraint("users_identity_subject_key", "users", type_="unique")
    op.drop_column("users", "identity_subject")

    for table, privileges, update_columns in OPERATOR_GRANTS:
        op.execute(f"GRANT {privileges} ON {table} TO {OPERATOR_ROLE}")
        op.execute(f"GRANT UPDATE ({update_columns}) ON {table} TO {OPERATOR_ROLE}")
    # Existence check of the Company in context only (no name, no HR data).
    op.execute(f"GRANT SELECT (id) ON companies TO {OPERATOR_ROLE}")

    op.execute(
        "CREATE OR REPLACE FUNCTION public.heroos_schema_contract() RETURNS integer "
        "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 2 $$"
    )


def downgrade() -> None:
    """Downgrade schema."""
    _lock()
    # Stop further operator changes first; a refusal below rolls this back too.
    for table, _, _ in OPERATOR_GRANTS:
        op.execute(f"REVOKE ALL ON {table} FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE ALL ON companies FROM {OPERATOR_ROLE}")

    # History, not just current state: a reactivated User or a Membership
    # granted after B1a leaves only active rows but must still block a rollback.
    # The last clauses are defense in depth in case the owner ever bypassed the
    # audit triggers: the legacy column holds one subject per User, one issuer.
    guard(
        f"""EXISTS (SELECT FROM identity_events
                    WHERE NOT (event_type = 'identity_bound' AND actor_kind = 'owner'
                               AND actor_reference = '{B1A_BACKFILL_REFERENCE}'))
            OR EXISTS (SELECT FROM membership_events)
            OR EXISTS (SELECT FROM users WHERE status <> 'active')
            OR EXISTS (SELECT FROM user_identities WHERE status <> 'active')
            OR EXISTS (SELECT FROM memberships WHERE status <> 'active')
            OR EXISTS (SELECT FROM users u
                       WHERE (SELECT count(*) FROM user_identities i
                              WHERE i.user_id = u.id) <> 1)
            OR (SELECT count(DISTINCT issuer) FROM user_identities) > 1""",
        "identity or Membership changes were made after the B1a backfill; the previous API "
        "would ignore that history, so roll forward instead "
        "(docs/operations/identity-provisioning.md)",
    )

    op.add_column("users", sa.Column("identity_subject", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE users u SET identity_subject = i.subject "
        "FROM user_identities i WHERE i.user_id = u.id"
    )
    op.alter_column("users", "identity_subject", nullable=False)
    op.create_unique_constraint("users_identity_subject_key", "users", ["identity_subject"])

    op.execute(
        "CREATE OR REPLACE FUNCTION public.heroos_schema_contract() RETURNS integer "
        "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 1 $$"
    )
