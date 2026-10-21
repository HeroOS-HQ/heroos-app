"""company blueprint context: website, summary, policies, HR support, primary contact (D5)

M2-NEW-03. The Company Blueprint becomes the canonical company context HeroOS
uses (``app.companies.blueprint``). Additive only: seven nullable columns on
``company_blueprints`` and nothing else. Every existing row keeps its values
and starts with the new fields unanswered (NULL); no Company, User,
Membership, Blueprint or Case row is created, changed or removed.

- ``website_url``: the company's website as a normalized ``http(s)`` URL (at
  most 500 characters, no whitespace or control character). Stored only:
  nothing fetches, crawls or reads it.
- ``company_summary``: what the company does and how the team is structured
  (plain text, line breaks allowed, at most 2,000 characters).
- ``policies_exist``: whether the company has HR policies (``yes``, ``no``,
  ``not_sure``; NULL is "not answered") and ``policy_context``, short notes
  such as the policies' names (at most 1,000 characters). Policy *documents*
  are not stored: their retention is undecided (PRIV-004).
- ``hr_support``: how the company handles HR (``none``, ``internal``,
  ``external``, ``mixed``, ``other``) and ``hr_support_notes`` (at most 500).
- ``primary_contact_membership_id``: the company's main contact, a Membership
  of the same Company. A Company-qualified foreign key
  (``company_id, primary_contact_membership_id``) to ``memberships`` makes a
  contact in another Company impossible, whatever the application does.

Grants: the API role may insert and update the new columns (column-level, like
the M1-10C profile columns); it already reads the whole row under RLS. The
identity operator gets nothing (it reads only the licensing and confirmation
columns). The jurisdiction confirmation is untouched.

``heroos_schema_contract()`` = 8: the M2-NEW-03 API needs these columns and
refuses to start on D4; the M2-NEW-02 API (contract >= 7) keeps working on D5
(it never names the new columns). Deploy order: D5, then the API and the
operator CLI, then the web app. Downgrade refuses once any new field holds a
value: roll forward instead.

Revision ID: 671bbbfc74ae
Revises: c4a7e2d9b310
Create Date: 2026-10-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "671bbbfc74ae"
down_revision: str | Sequence[str] | None = "c4a7e2d9b310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")
TABLE = "company_blueprints"

MAX_WEBSITE_URL = 500
MAX_COMPANY_SUMMARY = 2000
MAX_POLICY_CONTEXT = 1000
MAX_HR_SUPPORT_NOTES = 500
POLICIES_EXIST = ("yes", "no", "not_sure")
HR_SUPPORT = ("none", "internal", "external", "mixed", "other")
NEW_COLUMNS = (
    "website_url",
    "company_summary",
    "policies_exist",
    "policy_context",
    "hr_support",
    "hr_support_notes",
    "primary_contact_membership_id",
)
CONTACT_FK = "fk_company_blueprints_company_id_primary_contact_membership_id"

# Multi-line text: line breaks and tabs only. A URL: nothing invisible and no
# space at all (chr(1) to chr(32)). The classes are built with chr(): no
# backslash, and no "[:name:]" (SQLAlchemy would read ":name" as a bind
# parameter).
CONTROL = "('[' || chr(1) || '-' || chr(31) || chr(127) || '-' || chr(159) || ']')"
CONTROL_OR_SPACE = "('[' || chr(1) || '-' || chr(32) || chr(127) || '-' || chr(159) || ']')"
# Lengths as two comparisons, never BETWEEN (a dump and restore flattens it,
# and the backup/restore gate compares the catalogs exactly).
MULTI_LINE = (
    "{column} IS NULL OR (char_length({column}) >= 1 AND char_length({column}) <= {maximum} "
    "AND translate({column}, chr(9) || chr(10), '') !~ " + CONTROL + ")"
)
WEBSITE_URL_CHECK = (
    "website_url IS NULL OR ((left(website_url, 8) = 'https://' "
    "OR left(website_url, 7) = 'http://') "
    f"AND char_length(website_url) <= {MAX_WEBSITE_URL} "
    f"AND website_url !~ {CONTROL_OR_SPACE})"
)


def one_of_or_null(column: str, values: tuple[str, ...]) -> str:
    # Written out instead of IN (...): see app.db.models.audit.one_of.
    return f"{column} IS NULL OR " + " OR ".join(f"{column} = '{value}'" for value in values)


# Kept equal to app.db.models.company_blueprint (portable checks) plus the
# text checks only PostgreSQL can express.
CHECKS = (
    ("ck_company_blueprints_website_url", WEBSITE_URL_CHECK),
    (
        "ck_company_blueprints_company_summary",
        MULTI_LINE.format(column="company_summary", maximum=MAX_COMPANY_SUMMARY),
    ),
    ("ck_company_blueprints_policies_exist", one_of_or_null("policies_exist", POLICIES_EXIST)),
    (
        "ck_company_blueprints_policy_context",
        MULTI_LINE.format(column="policy_context", maximum=MAX_POLICY_CONTEXT),
    ),
    ("ck_company_blueprints_hr_support", one_of_or_null("hr_support", HR_SUPPORT)),
    (
        "ck_company_blueprints_hr_support_notes",
        MULTI_LINE.format(column="hr_support_notes", maximum=MAX_HR_SUPPORT_NOTES),
    ),
)


def columns(names: tuple[str, ...]) -> str:
    return ", ".join(names)


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true (fixed message)."""
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE, sa.Column("website_url", sa.String(length=MAX_WEBSITE_URL)))
    op.add_column(TABLE, sa.Column("company_summary", sa.Text()))
    op.add_column(TABLE, sa.Column("policies_exist", sa.String(length=16)))
    op.add_column(TABLE, sa.Column("policy_context", sa.Text()))
    op.add_column(TABLE, sa.Column("hr_support", sa.String(length=16)))
    op.add_column(TABLE, sa.Column("hr_support_notes", sa.Text()))
    op.add_column(TABLE, sa.Column("primary_contact_membership_id", sa.UUID()))
    for name, expression in CHECKS:
        op.create_check_constraint(name, TABLE, expression)
    # The contact is a Membership of the same Company (uq_memberships_company_id_id).
    op.create_foreign_key(
        CONTACT_FK,
        TABLE,
        "memberships",
        ["company_id", "primary_contact_membership_id"],
        ["company_id", "id"],
    )

    _grant()
    _set_schema_contract(8)


def _grant() -> None:
    for privilege in ("INSERT", "UPDATE"):
        op.execute(f"GRANT {privilege} ({columns(NEW_COLUMNS)}) ON {TABLE} TO {RUNTIME_ROLE}")

    new = ", ".join(f"'{name}'" for name in NEW_COLUMNS)
    runtime = f"(SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}')"
    guard(
        f"""EXISTS (
            SELECT FROM unnest(ARRAY[{new}]) AS c(name)
            WHERE NOT has_column_privilege('{RUNTIME_ROLE}', 'public.{TABLE}', c.name,
                                           'SELECT')
               OR NOT has_column_privilege('{RUNTIME_ROLE}', 'public.{TABLE}', c.name,
                                           'INSERT')
               OR NOT has_column_privilege('{RUNTIME_ROLE}', 'public.{TABLE}', c.name,
                                           'UPDATE')
               OR has_column_privilege('{OPERATOR_ROLE}', 'public.{TABLE}', c.name,
                                       'SELECT, INSERT, UPDATE, REFERENCES'))
        OR EXISTS (
            SELECT FROM pg_attribute a, aclexplode(a.attacl) x
            WHERE a.attrelid = 'public.{TABLE}'::regclass AND a.attname IN ({new})
              AND x.grantee <> {runtime})""",
        "unexpected privileges on the new company_blueprints columns",
    )
    # The jurisdiction confirmation stays out of the API role's reach.
    guard(
        f"""EXISTS (
            SELECT FROM unnest(ARRAY['employment_jurisdiction', 'confirmed_licensing_location',
                                     'confirmed_licensing_authority',
                                     'jurisdiction_confirmed_at']) AS c(name)
            WHERE has_column_privilege('{RUNTIME_ROLE}', 'public.{TABLE}', c.name,
                                       'INSERT, UPDATE'))""",
        "the API runtime role can write the jurisdiction confirmation",
    )
    roles = ", ".join(f"'{role}'" for role in SUPABASE_API_ROLES)
    guard(
        f"""EXISTS (
            SELECT FROM pg_roles r, pg_class c
            WHERE r.rolname IN ({roles})
              AND c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
              AND has_table_privilege(r.oid, c.oid,
                    'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'))""",
        "anon, authenticated or service_role hold privileges on a HeroOS table; revoke "
        "them (and their default privileges) before migrating",
    )


def _set_schema_contract(value: int) -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION public.heroos_schema_contract() RETURNS integer "
        f"LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT {value} $$"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE")
    answered = " OR ".join(f"{name} IS NOT NULL" for name in NEW_COLUMNS)
    guard(
        f"EXISTS (SELECT FROM {TABLE} WHERE {answered})",
        "company blueprints hold website, summary, policy, HR support or primary contact "
        "details; a rollback would delete them, so roll forward instead",
    )
    _set_schema_contract(7)
    op.drop_constraint(CONTACT_FK, TABLE, type_="foreignkey")
    for name, _ in reversed(CHECKS):
        op.drop_constraint(name, TABLE, type_="check")
    # Dropping a column also drops its column-level grants.
    for name in reversed(NEW_COLUMNS):
        op.drop_column(TABLE, name)
