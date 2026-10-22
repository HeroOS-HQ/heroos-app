"""Who may see workflow Cases (M2-01 interim least-privilege policy).

Until JJ approves dedicated HR access roles, Disciplinary Cases are visible
only to Company administrators: their titles, answers, conversation and
workflow metadata. Ordinary members can neither list nor open them, through
the workflow routes or the generic Case record routes. The workflow routes
enforce it with ``CompanyAdminDb`` (the role is re-checked inside the
request's transaction); the generic routes hide the restricted types.

An Ask HeroOS conversation's Case (chat-first, one conversation is one Case)
exists from the founder's first message, before HeroOS knows its workflow:
until then its type is ``unclassified``, restricted the same way.
"""

from typing import Final

from app.db.models.membership import ROLE_COMPANY_ADMIN

# A conversation's Case whose workflow isn't known yet (it takes the workflow's type later).
UNCLASSIFIED_CASE_TYPE: Final = "unclassified"
# Case types whose records only Company administrators may see.
RESTRICTED_CASE_TYPES: Final = frozenset({"disciplinary", UNCLASSIFIED_CASE_TYPE})


def may_access_case_type(role: str, case_type: str) -> bool:
    return role == ROLE_COMPANY_ADMIN or case_type not in RESTRICTED_CASE_TYPES


def hidden_case_types(role: str) -> frozenset[str]:
    """Case types to leave out of a listing for ``role``."""
    return frozenset() if role == ROLE_COMPANY_ADMIN else RESTRICTED_CASE_TYPES
