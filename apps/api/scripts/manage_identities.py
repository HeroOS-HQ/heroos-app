"""Identity operator CLI: provision users, bind identities, manage lifecycle (ADR-008).

Platform-operator tool. Not shipped as an API entrypoint and never reachable over
HTTP. It connects with a personal identity-operator login, a member of
``heroos_identity_operator``, never the API runtime role or the migration owner::

    export HEROOS_OPERATOR_DATABASE_URL='postgresql+psycopg://heroos_op_<handle>@<host>/<db>?sslmode=verify-full&sslrootcert=<ca>'
    # password from ~/.pgpass (0600), never on the command line
    uv run python -m scripts.manage_identities --expect-database <db> --reference HER-230 \\
        provision --company <uuid> --issuer <exact issuer> < subject.txt

External subjects are pseudonymous personal data: they are read from standard
input (one line), never from arguments (process lists, shell history), and are
never printed. Output is one JSON object with an outcome and internal IDs.

Before any change the CLI refuses unless:

- a non-local host is reached with ``sslmode=verify-full`` and the session is
  really encrypted;
- the login is an unprivileged identity operator (not superuser, BYPASSRLS,
  CREATEROLE, table owner or API runtime role);
- the identity schema contract is exactly 2 (migration B1b);
- the connected database is the one named by ``--expect-database``.

Each command is one transaction: the change reference (``--reference``, an issue
key) is attached first, and the database audit triggers write the event in the
same transaction. There is no delete command (PRIV-008, PRIV-020).
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from typing import Final
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db.runtime_role import (
    OPERATOR_SCHEMA_CONTRACT,
    IncompatibleSchemaError,
    UnsafeDatabaseRoleError,
    check_operator_role,
    check_schema_contract,
)
from app.identity import service
from app.identity.errors import IDENTITY_CONFLICT, IdentityOperationError
from app.identity.operator import set_actor_reference
from app.identity.validation import ACTOR_REFERENCE

OPERATOR_URL_ENV: Final = "HEROOS_OPERATOR_DATABASE_URL"
LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1", "db"})

EXIT_REFUSED: Final = 3
EXIT_OPERATION_REFUSED: Final = 4
EXIT_DATABASE_ERROR: Final = 5


class OperatorRefusal(Exception):
    """A pre-flight check failed. Messages never contain secrets or subjects."""


def check_transport_policy(url: URL) -> bool:
    """Return whether TLS is required; refuse unsafe configurations.

    Only loopback (and the local Compose ``db`` service) may connect without
    TLS. Every other host needs ``sslmode=verify-full`` (certificate and host
    name verified).
    """
    host = url.host
    if not host:
        raise OperatorRefusal(f"{OPERATOR_URL_ENV} must name the database host")
    if host in LOCAL_HOSTS:
        return False
    if url.query.get("sslmode") != "verify-full":
        raise OperatorRefusal("non-local operator connections require sslmode=verify-full")
    return True


def operator_url() -> URL:
    raw = os.environ.get(OPERATOR_URL_ENV, "").strip()
    if not raw:
        raise OperatorRefusal(f"{OPERATOR_URL_ENV} is not set")
    try:
        url = make_url(raw)
    except ArgumentError:
        raise OperatorRefusal(f"{OPERATOR_URL_ENV} is not a valid database URL") from None
    if not url.username:
        raise OperatorRefusal(f"{OPERATOR_URL_ENV} must name the operator login")
    return url


def preflight(engine: Engine, *, require_tls: bool, expect_database: str) -> None:
    with engine.connect() as connection:
        if require_tls and not connection.scalar(
            text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        ):
            raise OperatorRefusal("the database session is not encrypted")
        check_operator_role(connection)
        check_schema_contract(connection, minimum=OPERATOR_SCHEMA_CONTRACT, exact=True)
        database = connection.scalar(text("SELECT current_database()"))
        if database != expect_database:
            raise OperatorRefusal("connected database does not match --expect-database")


def read_subject() -> str:
    """One line from standard input; only the line ending is removed."""
    line = sys.stdin.readline()
    return line[:-1] if line.endswith("\n") else line


def _reference(value: str) -> str:
    if not ACTOR_REFERENCE.fullmatch(value):
        raise argparse.ArgumentTypeError("must be an issue key such as HER-230")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_identities",
        description="HeroOS identity operator CLI (subjects are read from stdin).",
    )
    parser.add_argument("--expect-database", required=True, help="database name to confirm")
    parser.add_argument(
        "--reference", required=True, type=_reference, help="change reference (issue key)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def company_identity(name: str, help_text: str) -> None:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--company", required=True, type=UUID)
        command.add_argument("--issuer", required=True)

    company_identity("provision", "new user + identity binding + Company Membership")
    company_identity("grant", "Company Membership for an existing, active identity")
    for name in ("revoke-membership", "reactivate-membership"):
        command = commands.add_parser(name)
        command.add_argument("--company", required=True, type=UUID)
        command.add_argument("--membership", required=True, type=UUID)
    bind = commands.add_parser("bind-identity", help="additional identity for an existing user")
    bind.add_argument("--user", required=True, type=UUID)
    bind.add_argument("--issuer", required=True)
    for name in ("revoke-identity", "reactivate-identity"):
        commands.add_parser(name).add_argument("--identity", required=True, type=UUID)
    for name in ("suspend-user", "reactivate-user"):
        commands.add_parser(name).add_argument("--user", required=True, type=UUID)
    return parser


Operation = Callable[[Session], service.OperationResult]


def operation(args: argparse.Namespace) -> Operation:
    match args.command:
        case "provision":
            subject = read_subject()
            return lambda s: service.provision_member(
                s, company_id=args.company, issuer=args.issuer, subject=subject
            )
        case "grant":
            subject = read_subject()
            return lambda s: service.grant_membership(
                s, company_id=args.company, issuer=args.issuer, subject=subject
            )
        case "revoke-membership":
            return lambda s: service.revoke_membership(
                s, company_id=args.company, membership_id=args.membership
            )
        case "reactivate-membership":
            return lambda s: service.reactivate_membership(
                s, company_id=args.company, membership_id=args.membership
            )
        case "bind-identity":
            subject = read_subject()
            return lambda s: service.bind_identity(
                s, user_id=args.user, issuer=args.issuer, subject=subject
            )
        case "revoke-identity":
            return lambda s: service.revoke_identity(s, identity_id=args.identity)
        case "reactivate-identity":
            return lambda s: service.reactivate_identity(s, identity_id=args.identity)
        case "suspend-user":
            return lambda s: service.suspend_user(s, user_id=args.user)
        case "reactivate-user":
            return lambda s: service.reactivate_user(s, user_id=args.user)
    raise AssertionError(args.command)


def _emit(payload: dict[str, str]) -> None:
    print(json.dumps(payload, sort_keys=True))


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        url = operator_url()
        require_tls = check_transport_policy(url)
    except OperatorRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    perform = operation(args)
    engine = create_engine(url, poolclass=NullPool)
    try:
        print(
            f"target: host={url.host} database={url.database} login={url.username}",
            file=sys.stderr,
        )
        try:
            preflight(engine, require_tls=require_tls, expect_database=args.expect_database)
        except (OperatorRefusal, UnsafeDatabaseRoleError, IncompatibleSchemaError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED

        with Session(engine, autoflush=False) as session:
            try:
                set_actor_reference(session, args.reference)
                result = perform(session)
                session.commit()
            except IdentityOperationError as exc:
                session.rollback()
                _emit({"command": args.command, "outcome": "refused", "code": exc.code})
                return EXIT_OPERATION_REFUSED
            except IntegrityError:
                # A concurrent operation won a uniqueness race.
                session.rollback()
                _emit({"command": args.command, "outcome": "refused", "code": IDENTITY_CONFLICT})
                return EXIT_OPERATION_REFUSED
    except DBAPIError as exc:
        # Never echo driver messages: they can quote values.
        state = getattr(exc.orig, "sqlstate", None) or "unknown"
        print(f"error: database error {type(exc.orig).__name__} ({state})", file=sys.stderr)
        return EXIT_DATABASE_ERROR
    finally:
        engine.dispose()

    _emit(
        {
            "command": args.command,
            "outcome": result.outcome,
            **{name: str(value) for name, value in result.ids.items()},
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
