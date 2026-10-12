"""add external identities, lifecycle and security audit (B1a: expand)

M1-10B, ADR-008. Compatible with the previous API (``371dd50``): that code still
finds every User through ``users.identity_subject``, which this revision keeps.
B1b (``09cb5ec569b9``) activates operator provisioning and removes the legacy
column; deploy the new API between the two.

What this revision adds:

- ``user_identities``: exact ``(issuer, subject)`` bindings to the stable
  ``users.id``; unique for all time; immutable ``user_id/issuer/subject``.
- Lifecycle: ``users.status`` (active/suspended), ``user_identities.status``
  and ``memberships.status`` (active/revoked). Nothing is deleted.
- ``heroos_identity_operator``: NOLOGIN group for the operator CLI. Its
  mutation grants arrive in B1b.
- Row-Level Security for the API role: suspended Users, revoked bindings and
  revoked Memberships are invisible to ``heroos_app_runtime`` (and so to any API
  revision). The API role loses INSERT/UPDATE/DELETE on ``memberships``:
  granting access is provisioning.
- Append-only audit: ``identity_events`` (global, owner-only) and
  ``membership_events`` (tenant-owned), written only by SECURITY DEFINER
  triggers that record ``session_user`` and a validated change reference.
- ``heroos_schema_contract()`` = 1.

Backfill (existing Users only): one active binding per User, keyed by the exact
legacy issuer. Required for non-empty data, and refused otherwise::

    alembic -x legacy_identity_issuer=<exact issuer> \\
            -x legacy_identity_user_count=<number of users> upgrade b8a11c15ed91

Everything runs in one transaction: any failed check leaves the database
exactly as it was. Downgrade refuses once any change other than this backfill
has been audited (see ``_refuse_unless_only_backfill_history``).

Revision ID: b8a11c15ed91
Revises: 97d4200fe7a2
Create Date: 2026-10-12 15:30:00.000000

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "b8a11c15ed91"
down_revision: str | Sequence[str] | None = "97d4200fe7a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
BACKFILL_REFERENCE = f"alembic:{revision}"
ISSUER_PATTERN = re.compile(r"https://[^\s?#'\"\\]+|urn:heroos:[a-z0-9:-]+")
MAX_ISSUER_LENGTH = 512


def one_of(column: str, values: tuple[str, ...]) -> str:
    """CHECK expression ``column = v1 OR ...``.

    Written out instead of ``IN (...)``: PostgreSQL deparses a varchar ``IN``
    check differently after a dump/restore, which would break the restore
    verification's exact catalog comparison.
    """
    return " OR ".join(f"{column} = '{value}'" for value in values)


IDENTITY_EVENT_TYPES = (
    "user_created",
    "user_suspended",
    "user_reactivated",
    "identity_bound",
    "identity_revoked",
    "identity_reactivated",
)
MEMBERSHIP_EVENT_TYPES = ("membership_granted", "membership_revoked", "membership_reactivated")
ACTOR_KINDS = ("owner", "operator", "api")


ACTOR_REFERENCE_CHECK = (
    "actor_reference ~ '^[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}$' "
    "OR (actor_kind = 'owner' AND actor_reference ~ '^alembic:[0-9a-f]{12}$')"
)

AUDIT_FUNCTIONS = (
    "heroos_audit_actor(regclass)",
    "heroos_audit_identity_change()",
    "heroos_audit_membership_change()",
    "heroos_identity_binding_immutable()",
    "heroos_audit_events_append_only()",
)


# Role relationships that would join the API runtime and identity operator
# capabilities: inheritance between the two groups in either direction, or any
# login (other than superusers and the migration owner running this) holding
# both. Checked on the server before any grant.
ROLE_SEPARATION_VIOLATED = f"""
    EXISTS (
        SELECT FROM pg_roles runtime, pg_roles operator
        WHERE runtime.rolname = '{RUNTIME_ROLE}' AND operator.rolname = '{OPERATOR_ROLE}'
          AND (pg_has_role(runtime.oid, operator.oid, 'MEMBER')
               OR pg_has_role(operator.oid, runtime.oid, 'MEMBER')
               OR EXISTS (
                    SELECT FROM pg_roles r
                    WHERE NOT r.rolsuper AND r.rolname <> current_user
                      AND r.oid NOT IN (runtime.oid, operator.oid)
                      AND pg_has_role(r.oid, runtime.oid, 'MEMBER')
                      AND pg_has_role(r.oid, operator.oid, 'MEMBER')))
    )
"""


class MigrationRefused(RuntimeError):
    """A safety precondition failed. Messages name options, never values."""


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true.

    Runs on the server, so the same check holds online and in rendered
    ``--sql`` scripts: an offline script cannot skip it. ``message`` is fixed
    text (no quotes, no data values).
    """
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def _backfill_arguments() -> tuple[str | None, int | None]:
    arguments = context.get_x_argument(as_dictionary=True)
    issuer = arguments.get("legacy_identity_issuer")
    count = arguments.get("legacy_identity_user_count")
    if (issuer is None) != (count is None):
        raise MigrationRefused(
            "supply both -x legacy_identity_issuer and -x legacy_identity_user_count, or neither"
        )
    if issuer is None or count is None:
        return None, None
    if len(issuer) > MAX_ISSUER_LENGTH or not ISSUER_PATTERN.fullmatch(issuer):
        raise MigrationRefused(
            "legacy_identity_issuer must be an exact https issuer or urn:heroos: URN "
            "(no whitespace, quotes, query or fragment)"
        )
    if not count.isdigit() or int(count) < 1:
        raise MigrationRefused("legacy_identity_user_count must be a positive integer")
    return issuer, int(count)


def upgrade() -> None:
    """Upgrade schema."""
    issuer, expected_count = _backfill_arguments()

    # No concurrent writer may add or change Users or Memberships while the
    # backfill is checked and written.
    op.execute("LOCK TABLE users, memberships IN ACCESS EXCLUSIVE MODE")
    if expected_count is None:
        guard(
            "EXISTS (SELECT FROM users)",
            "the database has existing users; supply -x legacy_identity_issuer=<exact issuer> "
            "and -x legacy_identity_user_count=<number of users>",
        )
    else:
        guard(
            f"(SELECT count(*) FROM users) <> {expected_count}",
            "legacy_identity_user_count does not match the existing users "
            "(wrong database, stale count, or no users to backfill)",
        )
        guard(
            "EXISTS (SELECT FROM users WHERE identity_subject = '')",
            "a legacy user has an empty identity_subject",
        )

    _create_operator_group()
    guard(
        ROLE_SEPARATION_VIOLATED,
        f"a role relationship joins {RUNTIME_ROLE} and {OPERATOR_ROLE} "
        "(inheritance in either direction, or a login in both); remove it first",
    )
    _add_lifecycle_columns()
    _create_identity_tables()
    _create_audit_functions_and_triggers()

    if issuer is not None:
        # Attributed to this migration by the audit trigger (actor_kind 'owner').
        op.execute(f"SELECT set_config('heroos.actor_reference', '{BACKFILL_REFERENCE}', true)")
        op.execute(
            sa.text(
                "INSERT INTO user_identities (id, user_id, issuer, subject, status) "
                "SELECT gen_random_uuid(), u.id, :issuer, u.identity_subject, 'active' "
                "FROM users u"
            ).bindparams(issuer=issuer)
        )
        _verify_backfill(expected_count)

    _enable_row_level_security()
    _grant()
    _create_schema_contract()
    _settle_privileges()


def _create_operator_group() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{OPERATOR_ROLE}') THEN
                CREATE ROLE {OPERATOR_ROLE}
                    NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
            -- A pre-existing role must not be privileged, able to log in, or
            -- hold the API runtime role (which would add HR data access).
            IF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{OPERATOR_ROLE}'
                  AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcanlogin)
            ) OR pg_has_role('{OPERATOR_ROLE}', '{RUNTIME_ROLE}', 'MEMBER') THEN
                RAISE EXCEPTION 'role % must be an unprivileged NOLOGIN group outside %',
                    '{OPERATOR_ROLE}', '{RUNTIME_ROLE}';
            END IF;
        END
        $$;
        """
    )


def _add_lifecycle_columns() -> None:
    op.add_column(
        "users",
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
    )
    op.add_column("users", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_users_status", "users", "status = 'active' OR status = 'suspended'"
    )
    op.create_check_constraint(
        "ck_users_suspended_at", "users", "(status = 'suspended') = (suspended_at IS NOT NULL)"
    )

    op.add_column(
        "memberships",
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
    )
    op.add_column("memberships", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_memberships_status", "memberships", "status = 'active' OR status = 'revoked'"
    )
    op.create_check_constraint(
        "ck_memberships_revoked_at",
        "memberships",
        "(status = 'revoked') = (revoked_at IS NOT NULL)",
    )
    op.create_unique_constraint("uq_memberships_company_id_id", "memberships", ["company_id", "id"])


def _event_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
    )


def _actor_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("db_role", sa.String(length=63), nullable=False),
        sa.Column("actor_reference", sa.String(length=64), nullable=False),
    )


def _create_identity_tables() -> None:
    timestamps = (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "user_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps,
        sa.CheckConstraint(
            "status = 'active' OR status = 'revoked'", name="ck_user_identities_status"
        ),
        sa.CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_user_identities_revoked_at"
        ),
        sa.CheckConstraint("issuer <> ''", name="ck_user_identities_issuer_not_empty"),
        sa.CheckConstraint("subject <> ''", name="ck_user_identities_subject_not_empty"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_user_identities_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_user_identities_issuer_subject"),
    )
    op.create_index(
        "uq_user_identities_active_user_issuer",
        "user_identities",
        ["user_id", "issuer"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "identity_events",
        *_event_columns(),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            one_of("event_type", IDENTITY_EVENT_TYPES),
            name="ck_identity_events_event_type",
        ),
        sa.CheckConstraint(
            one_of("actor_kind", ACTOR_KINDS),
            name="ck_identity_events_actor_kind",
        ),
        sa.CheckConstraint(ACTOR_REFERENCE_CHECK, name="ck_identity_events_actor_reference"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_identity_events_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["user_identities.id"],
            ondelete="RESTRICT",
            name="fk_identity_events_identity_id_user_identities",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "membership_events",
        *_event_columns(),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        *_actor_columns(),
        sa.CheckConstraint(
            one_of("event_type", MEMBERSHIP_EVENT_TYPES),
            name="ck_membership_events_event_type",
        ),
        sa.CheckConstraint(
            one_of("actor_kind", ACTOR_KINDS),
            name="ck_membership_events_actor_kind",
        ),
        sa.CheckConstraint(ACTOR_REFERENCE_CHECK, name="ck_membership_events_actor_reference"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
            name="fk_membership_events_company_id_companies",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
            name="fk_membership_events_company_id_membership_id_memberships",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_membership_events_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_audit_functions_and_triggers() -> None:
    # Every function pins search_path to '' and schema-qualifies objects
    # (pg_catalog is always searched first), so nothing can be shadowed.
    op.execute(
        f"""
        CREATE FUNCTION public.heroos_audit_actor(
            target regclass, OUT actor_kind text, OUT db_role text, OUT actor_reference text
        )
            LANGUAGE plpgsql STABLE
            SET search_path = ''
        AS $$
        DECLARE
            writer_is_superuser boolean;
        BEGIN
            -- session_user is the authenticated login; under SECURITY DEFINER
            -- current_user is the function owner, and SET ROLE cannot change it.
            db_role := session_user;
            SELECT r.rolsuper INTO writer_is_superuser
              FROM pg_catalog.pg_roles r WHERE r.rolname = session_user;
            IF coalesce(writer_is_superuser, false)
               OR pg_catalog.pg_has_role(
                    session_user,
                    (SELECT c.relowner FROM pg_catalog.pg_class c WHERE c.oid = target),
                    'MEMBER') THEN
                actor_kind := 'owner';
            ELSIF EXISTS (SELECT FROM pg_catalog.pg_roles r
                           WHERE r.rolname = '{OPERATOR_ROLE}'
                             AND pg_catalog.pg_has_role(session_user, r.oid, 'MEMBER')) THEN
                actor_kind := 'operator';
            ELSIF EXISTS (SELECT FROM pg_catalog.pg_roles r
                           WHERE r.rolname = '{RUNTIME_ROLE}'
                             AND pg_catalog.pg_has_role(session_user, r.oid, 'MEMBER')) THEN
                actor_kind := 'api';
            ELSE
                RAISE EXCEPTION 'heroos audit: unrecognized database writer'
                    USING ERRCODE = '42501';
            END IF;

            actor_reference := pg_catalog.current_setting('heroos.actor_reference', true);
            IF actor_reference IS NULL
               OR NOT (actor_reference ~ '^[A-Z][A-Z0-9]{{1,9}}-[0-9]{{1,7}}$'
                       OR (actor_kind = 'owner'
                           AND actor_reference ~ '^alembic:[0-9a-f]{{12}}$')) THEN
                RAISE EXCEPTION 'heroos audit: a valid heroos.actor_reference is required'
                    USING ERRCODE = '22023';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.heroos_audit_identity_change() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER
            SET search_path = ''
        AS $$
        DECLARE
            actor record;
            event text;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
                RETURN NULL;
            END IF;
            SELECT * INTO STRICT actor FROM public.heroos_audit_actor(TG_RELID::regclass);
            IF TG_TABLE_NAME = 'users' THEN
                event := CASE WHEN TG_OP = 'INSERT' THEN 'user_created'
                              WHEN NEW.status = 'suspended' THEN 'user_suspended'
                              ELSE 'user_reactivated' END;
                INSERT INTO public.identity_events
                    (event_type, user_id, identity_id, actor_kind, db_role, actor_reference)
                VALUES (event, NEW.id, NULL,
                        actor.actor_kind, actor.db_role, actor.actor_reference);
            ELSE
                event := CASE WHEN TG_OP = 'INSERT' THEN 'identity_bound'
                              WHEN NEW.status = 'revoked' THEN 'identity_revoked'
                              ELSE 'identity_reactivated' END;
                INSERT INTO public.identity_events
                    (event_type, user_id, identity_id, actor_kind, db_role, actor_reference)
                VALUES (event, NEW.user_id, NEW.id,
                        actor.actor_kind, actor.db_role, actor.actor_reference);
            END IF;
            RETURN NULL;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.heroos_audit_membership_change() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER
            SET search_path = ''
        AS $$
        DECLARE
            actor record;
            event text;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
                RETURN NULL;
            END IF;
            SELECT * INTO STRICT actor FROM public.heroos_audit_actor(TG_RELID::regclass);
            event := CASE WHEN TG_OP = 'INSERT' THEN 'membership_granted'
                          WHEN NEW.status = 'revoked' THEN 'membership_revoked'
                          ELSE 'membership_reactivated' END;
            -- company_id comes from the row that already passed the caller's
            -- tenant_isolation WITH CHECK.
            INSERT INTO public.membership_events
                (event_type, company_id, membership_id, user_id,
                 actor_kind, db_role, actor_reference)
            VALUES (event, NEW.company_id, NEW.id, NEW.user_id,
                    actor.actor_kind, actor.db_role, actor.actor_reference);
            RETURN NULL;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.heroos_identity_binding_immutable() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = ''
        AS $$
        BEGIN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.issuer IS DISTINCT FROM OLD.issuer
               OR NEW.subject IS DISTINCT FROM OLD.subject THEN
                RAISE EXCEPTION 'heroos: identity bindings are immutable'
                    USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.heroos_audit_events_append_only() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = ''
        AS $$
        BEGIN
            RAISE EXCEPTION 'heroos: audit events are append-only' USING ERRCODE = '42501';
        END
        $$;
        """
    )
    for function in AUDIT_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC")

    op.execute(
        "CREATE TRIGGER heroos_audit_users AFTER INSERT OR UPDATE OF status ON public.users "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_identity_change()"
    )
    op.execute(
        "CREATE TRIGGER heroos_audit_user_identities "
        "AFTER INSERT OR UPDATE OF status ON public.user_identities "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_identity_change()"
    )
    op.execute(
        "CREATE TRIGGER heroos_audit_memberships "
        "AFTER INSERT OR UPDATE OF status ON public.memberships "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_membership_change()"
    )
    op.execute(
        "CREATE TRIGGER heroos_identity_binding_immutable "
        "BEFORE UPDATE ON public.user_identities "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_identity_binding_immutable()"
    )
    for table in ("identity_events", "membership_events"):
        op.execute(
            f"CREATE TRIGGER heroos_append_only BEFORE UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_events_append_only()"
        )
        # TRUNCATE skips row triggers, so it gets its own statement trigger. It
        # also fires for cascaded truncation (e.g. TRUNCATE users CASCADE).
        op.execute(
            f"CREATE TRIGGER heroos_append_only_truncate BEFORE TRUNCATE ON public.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.heroos_audit_events_append_only()"
        )


def _verify_backfill(expected_count: object) -> None:
    guard(
        """EXISTS (
            SELECT FROM users u
            WHERE (SELECT count(*) FROM user_identities i WHERE i.user_id = u.id) <> 1
               OR NOT EXISTS (
                    SELECT FROM user_identities i
                    WHERE i.user_id = u.id AND i.subject = u.identity_subject
                      AND i.status = 'active'))""",
        "legacy identity backfill verification failed",
    )
    guard(
        f"""(SELECT count(*) FROM identity_events
             WHERE event_type = 'identity_bound'
               AND actor_reference = '{BACKFILL_REFERENCE}') <> {int(str(expected_count))}""",
        "legacy identity backfill audit verification failed",
    )


def _enable_row_level_security() -> None:
    # API role: only active Users and bindings are visible. Operator group: all
    # (it manages lifecycle). The owner bypasses RLS (not FORCE), as elsewhere.
    for table, policy_prefix in (("users", "users"), ("user_identities", "identities")):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {policy_prefix}_runtime_read ON {table} AS PERMISSIVE FOR SELECT "
            f"TO {RUNTIME_ROLE} USING (status = 'active')"
        )
        op.execute(
            f"CREATE POLICY {policy_prefix}_operator ON {table} AS PERMISSIVE FOR ALL "
            f"TO {OPERATOR_ROLE} USING (true) WITH CHECK (true)"
        )
    # Revoked Memberships are invisible to the API role whatever code runs.
    op.execute(
        f"CREATE POLICY lifecycle_active ON memberships AS RESTRICTIVE FOR SELECT "
        f"TO {RUNTIME_ROLE} USING (status = 'active')"
    )
    # Owner-only: RLS with no policy denies every other role on top of the
    # missing grants.
    op.execute("ALTER TABLE identity_events ENABLE ROW LEVEL SECURITY")
    # Tenant-owned: the standard single tenant_isolation policy.
    op.execute("ALTER TABLE membership_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON membership_events
            AS PERMISSIVE
            FOR ALL
            TO PUBLIC
            USING (company_id = heroos_current_company_id())
            WITH CHECK (company_id = heroos_current_company_id())
        """
    )


def _grant() -> None:
    # Granting Company access is provisioning: operator-only from B1b on.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON memberships FROM {RUNTIME_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {OPERATOR_ROLE}")
    for table in ("identity_events", "membership_events"):
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")


def _create_schema_contract() -> None:
    op.execute(
        "CREATE FUNCTION public.heroos_schema_contract() RETURNS integer "
        "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 1 $$"
    )
    op.execute("REVOKE ALL ON FUNCTION public.heroos_schema_contract() FROM PUBLIC")


NEW_TABLES = ("user_identities", "identity_events", "membership_events")
NEW_FUNCTIONS = (*AUDIT_FUNCTIONS, "heroos_schema_contract()")
# Supabase grants these roles table access through default privileges; they
# are not HeroOS roles and must hold nothing on HeroOS tables.
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")

_TABLE_OIDS = ", ".join(f"'public.{t}'::regclass" for t in NEW_TABLES)
_FUNCTION_OIDS = ", ".join(f"'public.{f}'::regprocedure" for f in NEW_FUNCTIONS)


def _settle_privileges() -> None:
    """Make the new objects' privileges exactly the intended ones.

    Default privileges (``ALTER DEFAULT PRIVILEGES``, e.g. Supabase's grants
    to ``anon``, ``authenticated`` and ``service_role``) can attach grants to
    every object this migration creates. Revoke whatever any non-owner role
    received, re-apply only the intended grants, then verify on the server.
    Portable: nothing here assumes those roles exist.
    """
    op.execute(
        f"""
        DO $$
        DECLARE
            entry record;
        BEGIN
            FOR entry IN
                SELECT DISTINCT acl.target, acl.grantee FROM (
                    SELECT 'TABLE ' || c.oid::regclass::text AS target,
                           a.grantee, c.relowner AS owner
                    FROM pg_class c, aclexplode(c.relacl) a
                    WHERE c.oid IN ({_TABLE_OIDS})
                    UNION ALL
                    SELECT 'FUNCTION ' || p.oid::regprocedure::text,
                           a.grantee, p.proowner
                    FROM pg_proc p, aclexplode(p.proacl) a
                    WHERE p.oid IN ({_FUNCTION_OIDS})
                ) acl
                WHERE acl.grantee <> acl.owner
            LOOP
                IF entry.grantee = 0 THEN
                    EXECUTE format('REVOKE ALL ON %s FROM PUBLIC', entry.target);
                ELSE
                    EXECUTE format('REVOKE ALL ON %s FROM %I',
                                   entry.target, pg_get_userbyid(entry.grantee));
                END IF;
            END LOOP;
        END
        $$;
        """
    )
    # The only intended grants on the new objects.
    op.execute(f"GRANT SELECT ON user_identities TO {RUNTIME_ROLE}")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.heroos_schema_contract() "
        f"TO {RUNTIME_ROLE}, {OPERATOR_ROLE}"
    )

    guard(
        f"""EXISTS (
            SELECT FROM pg_class c, aclexplode(c.relacl) a
            WHERE c.oid IN ({_TABLE_OIDS}) AND a.grantee <> c.relowner
              AND NOT (c.oid = 'public.user_identities'::regclass
                       AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}')
                       AND a.privilege_type = 'SELECT'))
        OR EXISTS (
            SELECT FROM pg_proc p, aclexplode(p.proacl) a
            WHERE p.oid IN ({_FUNCTION_OIDS}) AND a.grantee <> p.proowner
              AND NOT (p.oid = 'public.heroos_schema_contract()'::regprocedure
                       AND a.grantee IN (SELECT oid FROM pg_roles
                                         WHERE rolname IN ('{RUNTIME_ROLE}', '{OPERATOR_ROLE}'))
                       AND a.privilege_type = 'EXECUTE'))""",
        "unexpected privileges remain on the new identity or audit objects",
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


HISTORY_SINCE_BACKFILL = f"""
    EXISTS (SELECT FROM identity_events
            WHERE NOT (event_type = 'identity_bound' AND actor_kind = 'owner'
                       AND actor_reference = '{BACKFILL_REFERENCE}'))
    OR EXISTS (SELECT FROM membership_events)
    OR EXISTS (SELECT FROM users WHERE status <> 'active')
    OR EXISTS (SELECT FROM user_identities WHERE status <> 'active')
    OR EXISTS (SELECT FROM memberships WHERE status <> 'active')
"""


def refuse_unless_only_backfill_history() -> None:
    """Refuse a downgrade once any security-relevant change has been audited.

    Current state is not enough: a User suspended and later reactivated, or a
    Membership granted after B1a, leaves only active rows but has history the
    previous schema cannot represent or the previous API would ignore. The only
    tolerated events are this revision's own backfill. Non-active rows are
    checked too, in case the owner ever bypassed the audit triggers.
    """
    guard(
        HISTORY_SINCE_BACKFILL,
        "identity or Membership changes were made after the B1a backfill; a rollback could "
        "restore revoked access or drop audit records, so roll forward instead "
        "(docs/operations/identity-provisioning.md)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "LOCK TABLE users, memberships, user_identities, identity_events, membership_events "
        "IN ACCESS EXCLUSIVE MODE"
    )
    refuse_unless_only_backfill_history()

    op.execute("DROP FUNCTION public.heroos_schema_contract()")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {OPERATOR_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE, DELETE ON memberships TO {RUNTIME_ROLE}")

    op.execute("DROP POLICY lifecycle_active ON memberships")
    for table, policy_prefix in (("users", "users"), ("user_identities", "identities")):
        op.execute(f"DROP POLICY {policy_prefix}_runtime_read ON {table}")
        op.execute(f"DROP POLICY {policy_prefix}_operator ON {table}")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER heroos_audit_users ON public.users")
    op.execute("DROP TRIGGER heroos_audit_memberships ON public.memberships")

    # The legacy users.identity_subject column was never removed by B1a, so
    # dropping the bindings loses nothing the previous schema can represent.
    op.drop_table("membership_events")
    op.drop_table("identity_events")
    op.drop_index("uq_user_identities_active_user_issuer", table_name="user_identities")
    op.drop_table("user_identities")
    for function in AUDIT_FUNCTIONS:
        op.execute(f"DROP FUNCTION public.{function}")

    op.drop_constraint("uq_memberships_company_id_id", "memberships", type_="unique")
    op.drop_constraint("ck_memberships_revoked_at", "memberships", type_="check")
    op.drop_constraint("ck_memberships_status", "memberships", type_="check")
    op.drop_column("memberships", "revoked_at")
    op.drop_column("memberships", "status")
    op.drop_constraint("ck_users_suspended_at", "users", type_="check")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "status")
    # The heroos_identity_operator role is cluster-wide (shared by every
    # database on the server) and is left in place, like heroos_app_runtime.
