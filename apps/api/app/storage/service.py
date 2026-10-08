"""Company-authorized access to private objects.

The only application entry point to object storage::

    AuthenticatedCompanyContext -> CompanyScope -> PrivateObjectService
        -> StorageKey(companies/<scope.company_id>/<object uuid>) -> provider

The Company namespace always comes from ``scope.company_id``, which
``open_company_scope`` takes from the Membership-derived context. No method
accepts a Company, a key, a path or a filename from the caller. Object UUIDs are
generated here; a caller can only present one back as a ``UUID``.

Knowing another Company's object UUID grants nothing: the lookup resolves inside
the caller's own namespace, so the object is simply not found there, exactly as
for a UUID that never existed.
"""

from uuid import UUID, uuid4

from app.storage.base import PrivateObjectStorage
from app.storage.errors import ObjectNotFoundError, StorageError
from app.storage.keys import StorageKey
from app.tenancy.scope import CompanyScope


class PrivateObjectService:
    def __init__(self, storage: PrivateObjectStorage) -> None:
        self._storage = storage

    @staticmethod
    def _company(scope: CompanyScope) -> UUID:
        if not isinstance(scope, CompanyScope):
            raise StorageError("object access requires a CompanyScope")
        return scope.company_id

    @classmethod
    def _key(cls, scope: CompanyScope, object_id: UUID) -> StorageKey:
        return StorageKey.for_object(cls._company(scope), object_id)

    @classmethod
    def _existing_key(cls, scope: CompanyScope, object_id: UUID) -> StorageKey | None:
        """Key for a caller-presented object ID; ``None`` if it can name no object.

        A non-UUID or nil identifier is treated exactly like a missing object.
        """
        company_id = cls._company(scope)
        if not isinstance(object_id, UUID) or object_id.int == 0:
            return None
        return StorageKey.for_object(company_id, object_id)

    def store(self, scope: CompanyScope, data: bytes) -> UUID:
        """Store a new write-once object in the scope's Company; return its new UUID."""
        object_id = uuid4()
        self._storage.put(self._key(scope, object_id), data)
        return object_id

    def read(self, scope: CompanyScope, object_id: UUID) -> bytes:
        """Raises ``ObjectNotFoundError`` unless the object exists in this Company."""
        key = self._existing_key(scope, object_id)
        if key is None:
            raise ObjectNotFoundError("object not found")
        return self._storage.get(key)

    def exists(self, scope: CompanyScope, object_id: UUID) -> bool:
        key = self._existing_key(scope, object_id)
        return key is not None and self._storage.exists(key)

    def delete(self, scope: CompanyScope, object_id: UUID) -> bool:
        """``False`` if the object does not exist in this Company."""
        key = self._existing_key(scope, object_id)
        return key is not None and self._storage.delete(key)
