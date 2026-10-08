"""Company-scoped data access for tenant-owned entities.

Every function takes a ``CompanyScope`` and filters by ``scope.company_id`` in
addition to any resource ID: an ID alone never selects a row. A row owned by
another Company is indistinguishable from a missing one (``None`` / ``False``).
``company_id`` is always taken from the scope and can never be set or changed
through these functions.

Functions flush but never commit; the caller owns the transaction.
"""


class ResourceNotFoundError(LookupError):
    """A referenced resource does not exist in the caller's Company."""
