"""Object storage adapters."""

from .object_storage import ObjectStorage, ObjectStorageConfig, ObjectStoragePutResult
from .readiness import ObjectStorageReadinessProbe

__all__ = [
    "ObjectStorage",
    "ObjectStorageConfig",
    "ObjectStoragePutResult",
    "ObjectStorageReadinessProbe",
]
