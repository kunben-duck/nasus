"""Explicit operator configuration; no inferred host cache or mutable image tag."""
import os
from pathlib import Path

from ...domain.quality_loop.native_build import NATIVE_BUILD_ADAPTER
from ...domain.shared.native_build_source import byte_digest
from .native_maven_build import OfflineMavenNativeBuild
from .native_python_build import OfflinePythonNativeBuild
from ...domain.quality_loop.build_profiles import PYTHON_BUILD, build_profile


class ConfiguredNativeBuild:
    def for_adapter(self, adapter):
        build_profile(adapter)
        return ConfiguredPythonBuild() if adapter == PYTHON_BUILD else self

    def _builder(self):
        image = os.environ.get("NASUS_NATIVE_BUILD_IMAGE_ID", "")
        cache = os.environ.get("NASUS_NATIVE_BUILD_MAVEN_CACHE", "")
        if not image or not cache:
            raise ValueError("native build requires explicit operator image and cache configuration")
        timeout = int(os.environ.get("NASUS_NATIVE_BUILD_TIMEOUT", "180"))
        return OfflineMavenNativeBuild(image_id=image, maven_cache=Path(cache), timeout=timeout)

    def policy(self):
        builder = self._builder()
        return {"adapter": NATIVE_BUILD_ADAPTER, "image_id": builder.image_id,
            "cache_identity_hash": byte_digest(str(builder.maven_cache).encode()), "timeout_seconds": builder.timeout,
            "network": "none", "cache_access": "read_only", "cache_contents_attested": False}

    def build(self, request, *, require_work=None):
        return self._builder().build(request, require_work=require_work)


class ConfiguredPythonBuild:
    def _builder(self):
        return OfflinePythonNativeBuild(image_id=os.environ.get("NASUS_NATIVE_BUILD_PYTHON_IMAGE_ID", ""),
            dependency_lock_hash=os.environ.get("NASUS_NATIVE_BUILD_PYTHON_LOCK_HASH", ""),
            timeout=int(os.environ.get("NASUS_NATIVE_BUILD_TIMEOUT", "180")))

    def policy(self):
        builder = self._builder()
        return {"adapter": PYTHON_BUILD, "image_id": builder.image_id,
            "dependency_lock_hash": builder.dependency_lock_hash, "timeout_seconds": builder.timeout,
            "network": "none", "cache_access": "read_only", "cache_contents_attested": True}

    def build(self, request, *, require_work=None):
        return self._builder().build(request, require_work=require_work)
