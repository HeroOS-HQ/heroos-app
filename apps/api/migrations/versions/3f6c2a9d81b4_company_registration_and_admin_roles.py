"""company registration, Company administrators and jurisdiction readiness (C1)

M1-10C. Builds on M1-10B (ADR-008) and requires B1b (``09cb5ec569b9``). The
M1-10B API (``169261d``) keeps working on this schema; the M1-10C API requires
it (``heroos_schema_contract() = 3``).

What this revision adds:

- ``memberships.role``: ``member`` (default for every existing Membership: nobody
  becomes an administrator by migration) or ``company_admin``. The API role
  still has no write privilege on ``memberships``; the identity operator gains
  column-level ``UPDATE (role)``. Role changes are audited
  (``membership_role_changed``) and every Membership event records the role.
- Company Blueprint licensing and jurisdiction: the customer's licensing answer
  (``licensing_location``, ``licensing_authority``) and a trusted confirmation
  (``employment_jurisdiction`` with the licensing answer it was confirmed
  against and ``jurisdiction_confirmed_at``). Existing values are untouched;
  every existing Blueprint starts unconfirmed. ``primary_jurisdiction`` is
  kept as it is and never establishes a jurisdiction.
- One Blueprint per Company: every Company without one gets an empty Blueprint.
- Self-service founder registration: ``heroos_register_company(issuer, subject,
  name)``, a ``SECURITY DEFINER`` function and the API role's only way to create
  anything identity-related. For the verified identity the API passes, it
  creates (or, for an existing active User, reuses) the User and binding, a new
  Company with a server-generated id, its empty Blueprint and a
  ``company_admin`` Membership, in the caller's transaction. One self-service
  registration per person (``company_registrations``, unique per User,
  serialized by advisory locks on the identity and the User), so retries,
  concurrent submissions and other bindings of the same person return the
  same Company. It never attaches anyone to an existing Company.
  Audited as actor ``api`` with the reference ``registration:<uuid>``.
- ``heroos_identity_companies(issuer, subject)``: read-only workspace discovery,
  the caller's own active Memberships across Companies (which RLS hides).
- Operator-assisted registration stays available: ``INSERT (id, name)`` on
  ``companies`` and ``INSERT (id, company_id)`` on ``company_blueprints`` for
  the identity operator, under the tenant policy (one Company per
  transaction). The API role loses ``INSERT``/``DELETE`` on ``companies`` and
  may write every Blueprint column except the four confirmation columns
  (column-level grants).
- Jurisdiction confirmation by the identity operator: ``SELECT`` on the
  licensing and confirmation columns only (no business profile) and ``UPDATE``
  on the confirmation columns.
- ``company_events`` (tenant-owned, append-only): ``company_registered``,
  ``jurisdiction_confirmed``, ``jurisdiction_cleared``, written only by a
  ``SECURITY DEFINER`` trigger that records ``session_user`` and the validated
  change reference, exactly like the M1-10B audit tables.
- ``heroos_schema_contract()`` = 3.

Everything runs in one transaction and every check runs on the server, so a
rendered ``--sql`` script cannot skip one. Downgrade refuses once any
registration, role, licensing or confirmation history exists: roll forward.

Revision ID: 3f6c2a9d81b4
Revises: 09cb5ec569b9
Create Date: 2026-10-13 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f6c2a9d81b4"
down_revision: str | Sequence[str] | None = "09cb5ec569b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
# Supabase grants these roles table access through default privileges; they
# are not HeroOS roles and must hold nothing on HeroOS tables or functions.
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")

B1_ACTOR_REFERENCE_CHECK = (
    "actor_reference ~ '^[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}$' "
    "OR (actor_kind = 'owner' AND actor_reference ~ '^alembic:[0-9a-f]{12}$')"
)
# Self-service registrations are attributed to the API login and the
# registration's own id (company_registrations.id), never to free text.
REGISTRATION_REFERENCE = (
    "^registration:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
ACTOR_REFERENCE_CHECK = (
    B1_ACTOR_REFERENCE_CHECK
    + f" OR (actor_kind = 'api' AND actor_reference ~ '{REGISTRATION_REFERENCE}')"
)
AUDIT_TABLES_WITH_REFERENCES = ("identity_events", "membership_events")
ACTOR_KINDS = ("owner", "operator", "api")
MEMBERSHIP_ROLES = ("member", "company_admin")
B1_MEMBERSHIP_EVENT_TYPES = ("membership_granted", "membership_revoked", "membership_reactivated")
MEMBERSHIP_EVENT_TYPES = (*B1_MEMBERSHIP_EVENT_TYPES, "membership_role_changed")
COMPANY_EVENT_TYPES = ("company_registered", "jurisdiction_confirmed", "jurisdiction_cleared")
LICENSING_LOCATIONS = ("difc", "other", "not_sure")
EMPLOYMENT_JURISDICTIONS = ("uae_federal", "difc", "adgm", "other")

# The trusted confirmation: only the identity operator (and the owner) write it.
CONFIRMATION_COLUMNS = (
    "employment_jurisdiction",
    "confirmed_licensing_location",
    "confirmed_licensing_authority",
    "jurisdiction_confirmed_at",
)
# Everything the API role may insert or update on a Blueprint.
RUNTIME_BLUEPRINT_COLUMNS = (
    "id",
    "company_id",
    "legal_name",
    "primary_jurisdiction",
    "industry",
    "employee_count",
    "licensing_location",
    "licensing_authority",
    "created_at",
    "updated_at",
)
# What the identity operator needs to confirm a jurisdiction: the Company key,
# the customer's licensing answer and the confirmation. No business profile.
OPERATOR_BLUEPRINT_READ_COLUMNS = (
    "company_id",
    "licensing_location",
    "licensing_authority",
    *CONFIRMATION_COLUMNS,
)

NEW_TABLES = ("company_events", "company_registrations")
# The API role's two new capabilities; nothing else is callable by it.
API_FUNCTIONS = (
    "heroos_register_company(text, text, text)",
    "heroos_identity_companies(text, text)",
)
NEW_FUNCTIONS = ("heroos_audit_company_change()", *API_FUNCTIONS)


def one_of(column: str, values: tuple[str, ...]) -> str:
    """CHECK expression ``column = v1 OR ...``.

    Written out instead of ``IN (...)``: PostgreSQL deparses a varchar ``IN``
    check differently after a dump/restore, which would break the restore
    verification's exact catalog comparison.
    """
    return " OR ".join(f"{column} = '{value}'" for value in values)


def columns(names: tuple[str, ...]) -> str:
    return ", ".join(names)


# Every branch is definite (IS [NOT] NULL guards): a CHECK that evaluates to
# NULL passes. Kept equal to app.db.models.company_blueprint.
LICENSING_LOCATION_CHECK = "licensing_location IS NULL OR " + one_of(
    "licensing_location", LICENSING_LOCATIONS
)
LICENSING_AUTHORITY_CHECK = (
    "licensing_authority IS NULL OR (licensing_location IS NOT NULL "
    "AND licensing_location = 'other' AND licensing_authority <> '')"
)
EMPLOYMENT_JURISDICTION_CHECK = "employment_jurisdiction IS NULL OR " + one_of(
    "employment_jurisdiction", EMPLOYMENT_JURISDICTIONS
)
JURISDICTION_CONFIRMATION_CHECK = (
    "(employment_jurisdiction IS NULL AND jurisdiction_confirmed_at IS NULL "
    "AND confirmed_licensing_location IS NULL AND confirmed_licensing_authority IS NULL) "
    "OR (employment_jurisdiction IS NOT NULL AND jurisdiction_confirmed_at IS NOT NULL "
    "AND confirmed_licensing_location IS NOT NULL "
    "AND ((confirmed_licensing_location = 'difc' AND confirmed_licensing_authority IS NULL) "
    "OR (confirmed_licensing_location = 'other' AND confirmed_licensing_authority IS NOT NULL "
    "AND confirmed_licensing_authority <> '')))"
)
COMPANY_EVENT_JURISDICTION_CHECK = (
    "(event_type = 'jurisdiction_confirmed' AND jurisdiction IS NOT NULL AND ("
    + one_of("jurisdiction", EMPLOYMENT_JURISDICTIONS)
    + ")) OR (event_type <> 'jurisdiction_confirmed' AND jurisdiction IS NULL)"
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


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true.

    Runs on the server, so the same check holds online and in rendered
    ``--sql`` scripts. ``message`` is fixed text (no quotes, no data values).
    """
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def _lock() -> None:
    op.execute(
        "LOCK TABLE users, user_identities, companies, company_blueprints, memberships, "
        "identity_events, membership_events IN ACCESS EXCLUSIVE MODE"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _lock()
    # The operator grants below must never become reachable from the API role.
    guard(
        ROLE_SEPARATION_VIOLATED,
        f"a role relationship joins {RUNTIME_ROLE} and {OPERATOR_ROLE} "
        "(inheritance in either direction, or a login in both); remove it first",
    )

    _add_membership_role()
    _add_blueprint_licensing_and_confirmation()
    # One Blueprint per Company from here on (registration creates it with the
    # Company). Empty: nothing about an existing Company is assumed.
    op.execute(
        "INSERT INTO company_blueprints (id, company_id) "
        "SELECT gen_random_uuid(), c.id FROM companies c "
        "WHERE NOT EXISTS (SELECT FROM company_blueprints b WHERE b.company_id = c.id)"
    )
    _create_company_events()
    _extend_membership_events()
    _create_audit_functions_and_triggers()
    _create_company_registrations()
    _accept_registration_references()
    _create_api_functions()
    _grant()
    _set_schema_contract(3)
    _settle_privileges()


def _add_membership_role() -> None:
    op.add_column(
        "memberships",
        sa.Column("role", sa.String(length=32), server_default=sa.text("'member'"), nullable=False),
    )
    op.create_check_constraint(
        "ck_memberships_role", "memberships", one_of("role", MEMBERSHIP_ROLES)
    )


def _add_blueprint_licensing_and_confirmation() -> None:
    for name, length in (
        ("licensing_location", 16),
        ("licensing_authority", 120),
        ("employment_jurisdiction", 16),
        ("confirmed_licensing_location", 16),
        ("confirmed_licensing_authority", 120),
    ):
        op.add_column(
            "company_blueprints", sa.Column(name, sa.String(length=length), nullable=True)
        )
    op.add_column(
        "company_blueprints",
        sa.Column("jurisdiction_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, expression in (
        ("ck_company_blueprints_licensing_location", LICENSING_LOCATION_CHECK),
        ("ck_company_blueprints_licensing_authority", LICENSING_AUTHORITY_CHECK),
        ("ck_company_blueprints_employment_jurisdiction", EMPLOYMENT_JURISDICTION_CHECK),
        ("ck_company_blueprints_jurisdiction_confirmation", JURISDICTION_CONFIRMATION_CHECK),
    ):
        op.create_check_constraint(name, "company_blueprints", expression)


def _create_company_events() -> None:
    op.create_table(
        "company_events",
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
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), nullable=True),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("db_role", sa.String(length=63), nullable=False),
        sa.Column("actor_reference", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            one_of("event_type", COMPANY_EVENT_TYPES), name="ck_company_events_event_type"
        ),
        sa.CheckConstraint(one_of("actor_kind", ACTOR_KINDS), name="ck_company_events_actor_kind"),
        sa.CheckConstraint(ACTOR_REFERENCE_CHECK, name="ck_company_events_actor_reference"),
        sa.CheckConstraint(COMPANY_EVENT_JURISDICTION_CHECK, name="ck_company_events_jurisdiction"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
            name="fk_company_events_company_id_companies",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Tenant-owned: the standard single tenant_isolation policy. No role but the
    # owner holds any privilege on it (only the audit trigger writes it).
    op.execute("ALTER TABLE company_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON company_events
            AS PERMISSIVE
            FOR ALL
            TO PUBLIC
            USING (company_id = heroos_current_company_id())
            WITH CHECK (company_id = heroos_current_company_id())
        """
    )
    op.execute("REVOKE ALL ON company_events FROM PUBLIC")
    # Append-only, also for the owner (the M1-10B guard function).
    op.execute(
        "CREATE TRIGGER heroos_append_only BEFORE UPDATE OR DELETE ON public.company_events "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER heroos_append_only_truncate BEFORE TRUNCATE ON public.company_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.heroos_audit_events_append_only()"
    )


def _extend_membership_events() -> None:
    # Adding a nullable column and replacing a CHECK touches no row, so the
    # append-only row triggers are not involved. Earlier events keep NULL.
    op.add_column("membership_events", sa.Column("role", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        "ck_membership_events_role",
        "membership_events",
        "role IS NULL OR " + one_of("role", MEMBERSHIP_ROLES),
    )
    op.drop_constraint("ck_membership_events_event_type", "membership_events", type_="check")
    op.create_check_constraint(
        "ck_membership_events_event_type",
        "membership_events",
        one_of("event_type", MEMBERSHIP_EVENT_TYPES),
    )


MEMBERSHIP_AUDIT_FUNCTION = """
    CREATE OR REPLACE FUNCTION public.heroos_audit_membership_change() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = ''
    AS $$
    DECLARE
        actor record;
    BEGIN
        IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status
           AND NEW.role IS NOT DISTINCT FROM OLD.role THEN
            RETURN NULL;
        END IF;
        SELECT * INTO STRICT actor FROM public.heroos_audit_actor(TG_RELID::regclass);
        -- company_id comes from the row that already passed the caller's
        -- tenant_isolation WITH CHECK. One event per changed aspect.
        IF TG_OP = 'INSERT' THEN
            INSERT INTO public.membership_events
                (event_type, company_id, membership_id, user_id, role,
                 actor_kind, db_role, actor_reference)
            VALUES ('membership_granted', NEW.company_id, NEW.id, NEW.user_id, NEW.role,
                    actor.actor_kind, actor.db_role, actor.actor_reference);
            RETURN NULL;
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            INSERT INTO public.membership_events
                (event_type, company_id, membership_id, user_id, role,
                 actor_kind, db_role, actor_reference)
            VALUES (CASE WHEN NEW.status = 'revoked' THEN 'membership_revoked'
                         ELSE 'membership_reactivated' END,
                    NEW.company_id, NEW.id, NEW.user_id, NEW.role,
                    actor.actor_kind, actor.db_role, actor.actor_reference);
        END IF;
        IF NEW.role IS DISTINCT FROM OLD.role THEN
            INSERT INTO public.membership_events
                (event_type, company_id, membership_id, user_id, role,
                 actor_kind, db_role, actor_reference)
            VALUES ('membership_role_changed', NEW.company_id, NEW.id, NEW.user_id, NEW.role,
                    actor.actor_kind, actor.db_role, actor.actor_reference);
        END IF;
        RETURN NULL;
    END
    $$;
"""

# B1a's definition, restored by the downgrade.
B1_MEMBERSHIP_AUDIT_FUNCTION = """
    CREATE OR REPLACE FUNCTION public.heroos_audit_membership_change() RETURNS trigger
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


def _create_audit_functions_and_triggers() -> None:
    op.execute(MEMBERSHIP_AUDIT_FUNCTION)
    op.execute("DROP TRIGGER heroos_audit_memberships ON public.memberships")
    op.execute(
        "CREATE TRIGGER heroos_audit_memberships "
        "AFTER INSERT OR UPDATE OF status, role ON public.memberships "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_membership_change()"
    )

    # Pinned search_path and schema-qualified objects, like every audit function.
    op.execute(
        """
        CREATE FUNCTION public.heroos_audit_company_change() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER
            SET search_path = ''
        AS $$
        DECLARE
            actor record;
            event text;
            confirmed text;
            company uuid;
        BEGIN
            IF TG_TABLE_NAME = 'companies' THEN
                event := 'company_registered';
                company := NEW.id;
            ELSE
                IF NEW.employment_jurisdiction IS NOT DISTINCT FROM OLD.employment_jurisdiction
                   AND NEW.confirmed_licensing_location
                       IS NOT DISTINCT FROM OLD.confirmed_licensing_location
                   AND NEW.confirmed_licensing_authority
                       IS NOT DISTINCT FROM OLD.confirmed_licensing_authority
                   AND NEW.jurisdiction_confirmed_at
                       IS NOT DISTINCT FROM OLD.jurisdiction_confirmed_at THEN
                    RETURN NULL;
                END IF;
                company := NEW.company_id;
                IF NEW.employment_jurisdiction IS NULL THEN
                    event := 'jurisdiction_cleared';
                ELSE
                    event := 'jurisdiction_confirmed';
                    confirmed := NEW.employment_jurisdiction;
                END IF;
            END IF;
            SELECT * INTO STRICT actor FROM public.heroos_audit_actor(TG_RELID::regclass);
            -- Never copies customer-supplied text (the licensing authority).
            INSERT INTO public.company_events
                (event_type, company_id, jurisdiction, actor_kind, db_role, actor_reference)
            VALUES (event, company, confirmed,
                    actor.actor_kind, actor.db_role, actor.actor_reference);
            RETURN NULL;
        END
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.heroos_audit_company_change() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER heroos_audit_companies AFTER INSERT ON public.companies "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_company_change()"
    )
    op.execute(
        "CREATE TRIGGER heroos_audit_company_jurisdiction "
        f"AFTER UPDATE OF {columns(CONFIRMATION_COLUMNS)} ON public.company_blueprints "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_company_change()"
    )


def _create_company_registrations() -> None:
    """One row per self-service registration; at most one per User (person)."""
    op.create_table(
        "company_registrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["user_identities.id"],
            ondelete="RESTRICT",
            name="fk_company_registrations_identity_id_user_identities",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_company_registrations_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
            name="fk_company_registrations_company_id_companies",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
            name="fk_company_registrations_company_id_membership_id_memberships",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_company_registrations_user_id"),
        sa.UniqueConstraint("company_id", name="uq_company_registrations_company_id"),
    )
    # Tenant-owned and owner-only, like the audit tables: written only by
    # heroos_register_company, never changed afterwards.
    op.execute("ALTER TABLE company_registrations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON company_registrations
            AS PERMISSIVE
            FOR ALL
            TO PUBLIC
            USING (company_id = heroos_current_company_id())
            WITH CHECK (company_id = heroos_current_company_id())
        """
    )
    op.execute("REVOKE ALL ON company_registrations FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER heroos_append_only BEFORE UPDATE OR DELETE "
        "ON public.company_registrations "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER heroos_append_only_truncate BEFORE TRUNCATE "
        "ON public.company_registrations "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.heroos_audit_events_append_only()"
    )


def _audit_actor_function(api_reference: bool) -> str:
    """``heroos_audit_actor``: B1a's definition, plus (C1) registration references."""
    registration = (
        f"""
                       OR (actor_kind = 'api'
                           AND actor_reference ~ '{REGISTRATION_REFERENCE}')"""
        if api_reference
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.heroos_audit_actor(
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
                           AND actor_reference ~ '^alembic:[0-9a-f]{{12}}$'){registration}) THEN
                RAISE EXCEPTION 'heroos audit: a valid heroos.actor_reference is required'
                    USING ERRCODE = '22023';
            END IF;
        END
        $$;
    """


def _accept_registration_references() -> None:
    # CREATE OR REPLACE keeps the owner and the (owner-only) EXECUTE privilege.
    op.execute(_audit_actor_function(api_reference=True))
    for table in AUDIT_TABLES_WITH_REFERENCES:
        name = f"ck_{table}_actor_reference"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, ACTOR_REFERENCE_CHECK)


# The founder registration capability. Every object schema-qualified, pinned
# search_path, no dynamic SQL. Inputs are re-validated here (the API validates
# first): a malformed identity is refused like an inactive one (42501), a
# malformed name as invalid input (22023).
REGISTER_COMPANY_FUNCTION = r"""
    CREATE FUNCTION public.heroos_register_company(
        p_issuer text, p_subject text, p_company_name text
    ) RETURNS TABLE (
        outcome text, company_id uuid, user_id uuid, identity_id uuid, membership_id uuid
    )
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = ''
    AS $$
    #variable_conflict use_column
    DECLARE
        found_identity uuid;
        found_identity_status text;
        found_user uuid;
        found_user_status text;
        registration public.company_registrations%ROWTYPE;
        registration_id uuid := pg_catalog.gen_random_uuid();
        new_company uuid := pg_catalog.gen_random_uuid();
        new_membership uuid := pg_catalog.gen_random_uuid();
    BEGIN
        -- The identity exactly as the API's provider verified it: the B1a
        -- issuer rule. A backslash, chr(92), is tested apart: no backslash may
        -- appear in this SQL (Alembic's text() rewrites escapes).
        IF p_issuer IS NULL OR pg_catalog.length(p_issuer) > 512
           OR p_issuer !~ '^(https://[^[:space:]?#''"]+|urn:heroos:[a-z0-9:-]+)$'
           OR pg_catalog.strpos(p_issuer, pg_catalog.chr(92)) > 0
           OR p_subject IS NULL OR p_subject = '' OR pg_catalog.length(p_subject) > 255
           OR p_subject ~ '[[:cntrl:]]' OR p_subject ~ '^[[:space:]]|[[:space:]]$' THEN
            RAISE EXCEPTION 'heroos registration: not a valid verified identity'
                USING ERRCODE = '42501';
        END IF;
        IF p_company_name IS NULL OR p_company_name = ''
           OR pg_catalog.length(p_company_name) > 200
           OR p_company_name ~ '[[:cntrl:]]' OR p_company_name ~ '^[[:space:]]|[[:space:]]$' THEN
            RAISE EXCEPTION 'heroos registration: invalid Company name'
                USING ERRCODE = '22023';
        END IF;

        -- One registration at a time per identity: a retry or a concurrent
        -- submission waits here, then finds the first one's result. (An issuer
        -- never contains a space, so the key is unambiguous.)
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('heroos-registration ' || p_issuer || ' ' || p_subject, 0));

        SELECT i.id, i.status, u.id, u.status
          INTO found_identity, found_identity_status, found_user, found_user_status
          FROM public.user_identities i JOIN public.users u ON u.id = i.user_id
         WHERE i.issuer = p_issuer AND i.subject = p_subject;
        IF found_identity IS NOT NULL THEN
            -- Lifecycle wins: a revoked binding or suspended User registers nothing.
            IF found_identity_status <> 'active' OR found_user_status <> 'active' THEN
                RAISE EXCEPTION 'heroos registration: identity is not active'
                    USING ERRCODE = '42501';
            END IF;
            -- One self-service registration per person, whichever of their
            -- bindings (e.g. Auth0 and Cognito during M5) is used.
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('heroos-registration-user ' || found_user::text, 0));
            SELECT r.* INTO registration FROM public.company_registrations r
             WHERE r.user_id = found_user;
            IF registration.id IS NOT NULL THEN
                IF NOT EXISTS (SELECT FROM public.memberships m
                                WHERE m.id = registration.membership_id
                                  AND m.status = 'active') THEN
                    RAISE EXCEPTION 'heroos registration: the registered Membership is revoked'
                        USING ERRCODE = '42501';
                END IF;
                -- Only ever the person's own registration (identity_id: the
                -- binding used now).
                RETURN QUERY SELECT 'existing'::text, registration.company_id,
                                    registration.user_id, found_identity,
                                    registration.membership_id;
                RETURN;
            END IF;
        END IF;

        -- Attribution for the audit triggers: the API login (session_user) and
        -- this registration.
        PERFORM pg_catalog.set_config(
            'heroos.actor_reference', 'registration:' || registration_id::text, true);
        IF found_identity IS NULL THEN
            found_user := pg_catalog.gen_random_uuid();
            found_identity := pg_catalog.gen_random_uuid();
            INSERT INTO public.users (id) VALUES (found_user);
            INSERT INTO public.user_identities (id, user_id, issuer, subject)
            VALUES (found_identity, found_user, p_issuer, p_subject);
        END IF;
        -- Always a new Company with a server-generated id.
        INSERT INTO public.companies (id, name) VALUES (new_company, p_company_name);
        INSERT INTO public.company_blueprints (id, company_id)
        VALUES (pg_catalog.gen_random_uuid(), new_company);
        INSERT INTO public.memberships (id, company_id, user_id, role)
        VALUES (new_membership, new_company, found_user, 'company_admin');
        INSERT INTO public.company_registrations
            (id, identity_id, user_id, company_id, membership_id)
        VALUES (registration_id, found_identity, found_user, new_company, new_membership);
        RETURN QUERY SELECT 'created'::text, new_company, found_user, found_identity,
                            new_membership;
    END
    $$;
"""

IDENTITY_COMPANIES_FUNCTION = """
    CREATE FUNCTION public.heroos_identity_companies(p_issuer text, p_subject text)
        RETURNS TABLE (company_id uuid, company_name text, membership_id uuid, role text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = ''
    AS $$
        SELECT c.id, c.name::text, m.id, m.role::text
          FROM public.user_identities i
          JOIN public.users u ON u.id = i.user_id
          JOIN public.memberships m ON m.user_id = u.id
          JOIN public.companies c ON c.id = m.company_id
         WHERE i.issuer = p_issuer AND i.subject = p_subject
           AND i.status = 'active' AND u.status = 'active' AND m.status = 'active'
         ORDER BY c.name, c.id
    $$;
"""


def _create_api_functions() -> None:
    op.execute(REGISTER_COMPANY_FUNCTION)
    op.execute(IDENTITY_COMPANIES_FUNCTION)
    # A new function is executable by PUBLIC until revoked (an implicit ACL the
    # settle step below cannot see); EXECUTE is granted to the API role only.
    for function in API_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC")


def _grant() -> None:
    # API role: no direct Company creation or deletion (self-service registration
    # goes only through heroos_register_company), and no write access to the
    # trusted jurisdiction confirmation.
    op.execute(f"REVOKE INSERT, DELETE ON companies FROM {RUNTIME_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE ON company_blueprints FROM {RUNTIME_ROLE}")
    for privilege in ("INSERT", "UPDATE"):
        op.execute(
            f"GRANT {privilege} ({columns(RUNTIME_BLUEPRINT_COLUMNS)}) "
            f"ON company_blueprints TO {RUNTIME_ROLE}"
        )

    # Identity operator: registration, the administrator role and the
    # jurisdiction confirmation. Writes stay under the tenant_isolation policy.
    op.execute(f"GRANT INSERT (id, name) ON companies TO {OPERATOR_ROLE}")
    op.execute(f"GRANT INSERT (id, company_id) ON company_blueprints TO {OPERATOR_ROLE}")
    op.execute(
        f"GRANT SELECT ({columns(OPERATOR_BLUEPRINT_READ_COLUMNS)}) "
        f"ON company_blueprints TO {OPERATOR_ROLE}"
    )
    op.execute(
        f"GRANT UPDATE ({columns((*CONFIRMATION_COLUMNS, 'updated_at'))}) "
        f"ON company_blueprints TO {OPERATOR_ROLE}"
    )
    op.execute(f"GRANT UPDATE (role) ON memberships TO {OPERATOR_ROLE}")

    confirmation = ", ".join(f"'{name}'" for name in CONFIRMATION_COLUMNS)
    guard(
        f"""EXISTS (
            SELECT FROM unnest(ARRAY[{confirmation}]) AS c(name)
            WHERE has_column_privilege('{RUNTIME_ROLE}', 'public.company_blueprints', c.name,
                                       'INSERT, UPDATE'))
        OR has_table_privilege('{RUNTIME_ROLE}', 'public.companies', 'INSERT, DELETE, TRUNCATE')
        OR has_table_privilege('{RUNTIME_ROLE}', 'public.memberships',
                               'INSERT, UPDATE, DELETE, TRUNCATE')
        OR has_column_privilege('{RUNTIME_ROLE}', 'public.memberships', 'role', 'UPDATE')""",
        "the API runtime role can still create Companies, change Memberships or write the "
        "jurisdiction confirmation; remove those grants first",
    )


def _set_schema_contract(value: int) -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION public.heroos_schema_contract() RETURNS integer "
        f"LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT {value} $$"
    )


_TABLE_OIDS = ", ".join(f"'public.{t}'::regclass" for t in NEW_TABLES)
_FUNCTION_OIDS = ", ".join(f"'public.{f}'::regprocedure" for f in NEW_FUNCTIONS)


def _settle_privileges() -> None:
    """Make the new objects' privileges exactly the intended ones (none).

    Default privileges (``ALTER DEFAULT PRIVILEGES``, e.g. Supabase's grants to
    ``anon``, ``authenticated`` and ``service_role``) can attach grants to every
    object this migration creates. Revoke whatever any non-owner role received,
    then verify on the server. Portable: nothing assumes those roles exist.
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
    for function in API_FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{function} TO {RUNTIME_ROLE}")
    api_function_oids = ", ".join(f"'public.{f}'::regprocedure" for f in API_FUNCTIONS)
    guard(
        f"""EXISTS (
            SELECT FROM pg_class c, aclexplode(c.relacl) a
            WHERE c.oid IN ({_TABLE_OIDS}) AND a.grantee <> c.relowner)
        OR EXISTS (
            SELECT FROM pg_proc p, aclexplode(p.proacl) a
            WHERE p.oid IN ({_FUNCTION_OIDS}) AND a.grantee <> p.proowner
              AND NOT (p.oid IN ({api_function_oids})
                       AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}')
                       AND a.privilege_type = 'EXECUTE'))""",
        "unexpected privileges remain on the new Company registration or audit objects",
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


# Anything the previous schema cannot represent, or whose audit record a
# rollback would drop. Current state and history both count.
HISTORY_SINCE_C1 = """
    EXISTS (SELECT FROM company_events)
    OR EXISTS (SELECT FROM company_registrations)
    OR EXISTS (SELECT FROM identity_events WHERE actor_reference LIKE 'registration:%')
    OR EXISTS (SELECT FROM membership_events WHERE role IS NOT NULL)
    OR EXISTS (SELECT FROM memberships WHERE role <> 'member')
    OR EXISTS (SELECT FROM company_blueprints
               WHERE licensing_location IS NOT NULL OR licensing_authority IS NOT NULL
                  OR employment_jurisdiction IS NOT NULL
                  OR confirmed_licensing_location IS NOT NULL
                  OR confirmed_licensing_authority IS NOT NULL
                  OR jurisdiction_confirmed_at IS NOT NULL)
"""


def downgrade() -> None:
    """Downgrade schema."""
    _lock()
    op.execute("LOCK TABLE company_events, company_registrations IN ACCESS EXCLUSIVE MODE")
    guard(
        HISTORY_SINCE_C1,
        "Company registrations, role changes, licensing answers or jurisdiction "
        "confirmations exist since C1; a rollback would drop them or their audit records, "
        "so roll forward instead (docs/operations/company-registration.md)",
    )

    _set_schema_contract(2)

    # Table-level REVOKE also removes the column-level grants.
    op.execute(f"REVOKE INSERT ON companies FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE ALL ON company_blueprints FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE UPDATE (role) ON memberships FROM {OPERATOR_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE ON company_blueprints FROM {RUNTIME_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE ON company_blueprints TO {RUNTIME_ROLE}")
    op.execute(f"GRANT INSERT, DELETE ON companies TO {RUNTIME_ROLE}")

    op.execute("DROP TRIGGER heroos_audit_company_jurisdiction ON public.company_blueprints")
    op.execute("DROP TRIGGER heroos_audit_companies ON public.companies")
    op.execute("DROP TRIGGER heroos_audit_memberships ON public.memberships")
    op.execute(B1_MEMBERSHIP_AUDIT_FUNCTION)
    op.execute(
        "CREATE TRIGGER heroos_audit_memberships "
        "AFTER INSERT OR UPDATE OF status ON public.memberships "
        "FOR EACH ROW EXECUTE FUNCTION public.heroos_audit_membership_change()"
    )
    for function in API_FUNCTIONS:
        op.execute(f"DROP FUNCTION public.{function}")
    op.drop_table("company_registrations")
    op.drop_table("company_events")
    op.execute("DROP FUNCTION public.heroos_audit_company_change()")
    for table in AUDIT_TABLES_WITH_REFERENCES:
        name = f"ck_{table}_actor_reference"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, B1_ACTOR_REFERENCE_CHECK)
    op.execute(_audit_actor_function(api_reference=False))

    op.drop_constraint("ck_membership_events_event_type", "membership_events", type_="check")
    op.create_check_constraint(
        "ck_membership_events_event_type",
        "membership_events",
        one_of("event_type", B1_MEMBERSHIP_EVENT_TYPES),
    )
    op.drop_constraint("ck_membership_events_role", "membership_events", type_="check")
    op.drop_column("membership_events", "role")

    for name in (
        "ck_company_blueprints_jurisdiction_confirmation",
        "ck_company_blueprints_employment_jurisdiction",
        "ck_company_blueprints_licensing_authority",
        "ck_company_blueprints_licensing_location",
    ):
        op.drop_constraint(name, "company_blueprints", type_="check")
    for name in (
        "jurisdiction_confirmed_at",
        "confirmed_licensing_authority",
        "confirmed_licensing_location",
        "employment_jurisdiction",
        "licensing_authority",
        "licensing_location",
    ):
        op.drop_column("company_blueprints", name)
    # The empty Blueprints added for Companies without one are kept: they are
    # valid rows of the previous schema.

    op.drop_constraint("ck_memberships_role", "memberships", type_="check")
    op.drop_column("memberships", "role")
