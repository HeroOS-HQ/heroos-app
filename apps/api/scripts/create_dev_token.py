"""Issue a short-lived local development bearer token.

Usage (from apps/api, or ``make dev-token SUBJECT=...`` from the repo root):

    uv run python -m scripts.create_dev_token <identity-subject> [--minutes 15]

Requires HEROOS_ENV=development, HEROOS_AUTH_PROVIDER=development and
HEROOS_DEV_AUTH_SECRET. The token only authenticates ``identity-subject``: Company
access still needs a matching ``users.identity_subject`` row and a Membership.
This script is not shipped in the API image and no endpoint mints tokens.
"""

import argparse
import sys
from datetime import timedelta

from pydantic import ValidationError

from app.auth.providers.development import (
    DEFAULT_DEVELOPMENT_TOKEN_LIFETIME,
    issue_development_token,
)
from app.core.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("subject", help="identity subject (users.identity_subject)")
    parser.add_argument(
        "--minutes",
        type=int,
        default=int(DEFAULT_DEVELOPMENT_TOKEN_LIFETIME.total_seconds() // 60),
        help="token lifetime in minutes (max 60)",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()  # type: ignore[call-arg]  # values come from the environment
    except ValidationError as exc:
        # Settings errors never include input values, so this cannot print secrets.
        print(f"Refusing: invalid configuration.\n{exc}", file=sys.stderr)
        return 1
    if (
        settings.heroos_env != "development"
        or settings.heroos_auth_provider != "development"
        or settings.heroos_dev_auth_secret is None
    ):
        print(
            "Refusing: requires HEROOS_ENV=development, HEROOS_AUTH_PROVIDER=development "
            "and HEROOS_DEV_AUTH_SECRET.",
            file=sys.stderr,
        )
        return 1

    print(
        issue_development_token(
            environment=settings.heroos_env,
            secret=settings.heroos_dev_auth_secret,
            subject=args.subject,
            lifetime=timedelta(minutes=args.minutes),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
