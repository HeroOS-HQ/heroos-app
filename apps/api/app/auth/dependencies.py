"""FastAPI dependencies for authenticated, Company-authorized requests.

Protected routes take a ``{company_id}`` path parameter and depend on
``CompanyContext``::

    @router.get("/companies/{company_id}/cases")
    def list_cases(context: CompanyContext) -> ...: ...

Failures are deliberately generic: 401 for any authentication failure, 403 for
any authorization failure. Credentials are never logged or echoed.
"""

import logging
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedCompanyContext, ResolvedUser, VerifiedIdentity
from app.auth.providers import AuthenticationProvider, build_authentication_provider
from app.auth.service import authorize_company, resolve_user
from app.core.config import settings
from app.db.session import get_db
from app.observability.context import record_authorized_company

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@lru_cache(maxsize=1)
def get_authentication_provider() -> AuthenticationProvider | None:
    return build_authentication_provider(settings)


def get_verified_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    provider: Annotated[AuthenticationProvider | None, Depends(get_authentication_provider)],
) -> VerifiedIdentity:
    if provider is None:
        logger.error("Rejected protected request: no authentication provider is configured")
        raise _unauthenticated()
    if credentials is None:
        raise _unauthenticated()
    try:
        return provider.authenticate(credentials.credentials)
    except AuthenticationError as exc:
        logger.info("Authentication rejected: %s", exc.reason)
        raise _unauthenticated() from None


def get_current_user(
    identity: Annotated[VerifiedIdentity, Depends(get_verified_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> ResolvedUser:
    try:
        return resolve_user(db, identity)
    except AuthorizationError as exc:
        logger.info("Authorization denied: %s", exc.reason)
        raise _forbidden() from None


def get_authenticated_company_context(
    company_id: UUID,
    user: Annotated[ResolvedUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AuthenticatedCompanyContext:
    try:
        context = authorize_company(db, user, company_id)
    except AuthorizationError as exc:
        logger.info("Authorization denied: %s (company_id=%s)", exc.reason, company_id)
        raise _forbidden() from None
    record_authorized_company(context)
    return context


CompanyContext = Annotated[AuthenticatedCompanyContext, Depends(get_authenticated_company_context)]
