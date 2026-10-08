"""FastAPI dependency for Company-authorized private object access.

Routes that handle private objects depend on both ``CompanyDb`` (trusted
Company scope) and ``ObjectStorage``::

    @router.get("/companies/{company_id}/objects/{object_id}")
    def read_object(object_id: UUID, scope: CompanyDb, objects: ObjectStorage) -> ...:
        data = objects.read(scope, object_id)   # ObjectNotFoundError -> 404

No such production route exists in M1; the HeroOS Document domain is M2 work.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.storage.base import PrivateObjectStorage
from app.storage.errors import StorageConfigurationError
from app.storage.factory import build_private_object_storage
from app.storage.service import PrivateObjectService


@lru_cache(maxsize=1)
def get_private_object_storage() -> PrivateObjectStorage | None:
    return build_private_object_storage(settings)


def get_private_object_service() -> PrivateObjectService:
    storage = get_private_object_storage()
    if storage is None:
        # Fail closed: no provider configured means no object access at all.
        raise StorageConfigurationError("private object storage is not configured")
    return PrivateObjectService(storage)


ObjectStorage = Annotated[PrivateObjectService, Depends(get_private_object_service)]
