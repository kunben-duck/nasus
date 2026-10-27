from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.code_provider_protocol import CodeProviderProtocolReceipt


def receipt():
    return CodeProviderProtocolReceipt("codebase-memory", "2024-11-05", "codebase-memory-mcp", "0.10.0",
        "codebase-memory-mcp 0.8.1", "sha256:" + "a" * 64, 14,
        ("prepare_index", "entities", "relations", "locate"), ("cli_mcp_version_mismatch",))


@pytest.mark.parametrize("changes", [
    {"protocol_version": "latest"}, {"server_name": "../source"}, {"server_version": "bad\nversion"},
    {"tool_count": True}, {"tool_count": 0}, {"tool_count": 129}, {"tools_schema_hash": "bad"},
    {"schema": "unknown"}, {"scope": "approved_knowledge"}, {"verified_operations": ("execute_target",)},
    {"verified_operations": ()}, {"gaps": ["unknown"]}, {"gaps": ("duplicate", "duplicate")},
])
def test_invalid_native_contract_receipts_cannot_be_persisted(changes):
    with pytest.raises(ValueError):
        replace(receipt(), **changes)


def test_protocol_receipt_hash_binds_all_observed_metadata_without_native_text():
    original = receipt()
    for changes in ({"server_version": "0.11.0"}, {"tool_count": 15}, {"protocol_version": "2025-06-18"},
                    {"tools_schema_hash": "sha256:" + "b" * 64}, {"gaps": ()}, {"cli_version": "different-build"}):
        assert replace(original, **changes).digest != original.digest
    assert original.payload()["verified_operations"] == ["prepare_index", "entities", "relations", "locate"]
    assert original.payload()["scope"] != "approved_knowledge"
