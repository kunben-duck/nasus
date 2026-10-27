"""Explicit operator selection; no installation, model calls or default-provider switch."""
from pathlib import Path
import tempfile

from .codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from .codegraph_sdk_code_intelligence import CodeGraphSDKCodeIntelligenceAdapter, CodeGraphSDKConfig


def configured_code_graph(config, *, max_files, max_source_bytes):
    if config.mode == "disabled":
        return None
    if config.provider == "codebase-memory":
        return CodebaseMemoryCodeIntelligenceAdapter(config)
    if config.provider != "codegraph":
        raise ValueError("unsupported code graph provider")
    if not config.sdk_package_path or not config.sdk_platform_path or not config.sdk_runtime_hash:
        raise ValueError("CodeGraph SDK selection requires explicit package, platform and reviewed runtime hash")
    return CodeGraphSDKCodeIntelligenceAdapter(CodeGraphSDKConfig(
        config.sdk_package_path, config.sdk_platform_path,
        config.cache_dir or Path(tempfile.gettempdir()) / "nasus-codegraph",
        config.sdk_runtime_hash, max_entities=config.max_entities, max_relationships=config.max_relationships,
        max_files=max_files, max_source_bytes=max_source_bytes,
        timeout_seconds=config.timeout_seconds, page_size=config.page_size))
