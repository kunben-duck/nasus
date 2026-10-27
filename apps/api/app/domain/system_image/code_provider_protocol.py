"""Advertised native contracts are not business or graph-completeness authority."""
from dataclasses import asdict, dataclass
import re
from typing import Union

from .code_provider import CodeProjectionGap, CodeProviderCapabilities
from .source_snapshots import snapshot_digest


@dataclass(frozen=True)
class CodeProviderProtocolReceipt:
    provider: str
    protocol_version: str
    server_name: str
    server_version: str
    cli_version: str
    tools_schema_hash: str
    tool_count: int
    verified_operations: tuple[str, ...]
    gaps: tuple[str, ...] = ()
    schema: str = "nasus.code-provider-protocol.v1"
    scope: str = "advertised_tool_contract_not_language_or_runtime_completeness"

    def __post_init__(self):
        CodeProviderCapabilities(self.provider, self.server_version, self.verified_operations)
        CodeProviderCapabilities(self.provider, self.cli_version, ())
        if type(self.tools_schema_hash) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", self.tools_schema_hash) is None:
            raise ValueError("invalid native code provider contract digest")
        if (type(self.protocol_version) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.protocol_version) is None
                or type(self.server_name) is not str or re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", self.server_name) is None
                or type(self.tool_count) is not int or not 1 <= self.tool_count <= 128
                or self.schema != "nasus.code-provider-protocol.v1"
                or self.scope != "advertised_tool_contract_not_language_or_runtime_completeness"
                or not self.verified_operations or type(self.gaps) is not tuple or len(self.gaps) > 16
                or any(type(gap) is not str for gap in self.gaps) or len(set(self.gaps)) != len(self.gaps)):
            raise ValueError("invalid native code provider contract receipt")
        for gap in self.gaps:
            CodeProjectionGap(gap)

    def payload(self):
        return {**asdict(self), "verified_operations": list(self.verified_operations), "gaps": list(self.gaps)}

    @property
    def digest(self):
        return snapshot_digest(self.payload())


@dataclass(frozen=True)
class CodeProviderSDKReceipt:
    provider: str
    package_name: str
    package_version: str
    entry_point: str
    contract_hash: str
    runtime_hash: str
    public_operations: tuple[str, ...]
    gaps: tuple[str, ...] = ()
    schema: str = "nasus.code-provider-sdk-contract.v1"
    scope: str = "exercised_public_sdk_projection_not_language_or_runtime_completeness"

    def __post_init__(self):
        CodeProviderCapabilities(self.provider, self.package_version, ())
        if (type(self.package_name) is not str
                or re.fullmatch(r"(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]{1,128}", self.package_name) is None
                or self.entry_point != "package_public_entry"
                or self.schema != "nasus.code-provider-sdk-contract.v1"
                or self.scope != "exercised_public_sdk_projection_not_language_or_runtime_completeness"
                or type(self.public_operations) is not tuple or not 1 <= len(self.public_operations) <= 32
                or any(type(item) is not str or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,127}", item) is None
                       for item in self.public_operations)
                or len(set(self.public_operations)) != len(self.public_operations)
                or type(self.gaps) is not tuple or len(self.gaps) > 16
                or any(type(gap) is not str for gap in self.gaps) or len(set(self.gaps)) != len(self.gaps)):
            raise ValueError("invalid public SDK contract receipt")
        for digest in (self.contract_hash, self.runtime_hash):
            if type(digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
                raise ValueError("invalid public SDK contract digest")
        for gap in self.gaps:
            CodeProjectionGap(gap)

    def payload(self):
        return {**asdict(self), "public_operations": list(self.public_operations), "gaps": list(self.gaps)}

    @property
    def digest(self):
        return snapshot_digest(self.payload())


CodeProviderContractReceipt = Union[CodeProviderProtocolReceipt, CodeProviderSDKReceipt]
CODE_PROVIDER_CONTRACT_TYPES = (CodeProviderProtocolReceipt, CodeProviderSDKReceipt)


def read_code_provider_contract(payload) -> CodeProviderContractReceipt:
    if type(payload) is not dict or type(payload.get("gaps")) is not list:
        raise ValueError("invalid native contract payload")
    if payload.get("schema") == "nasus.code-provider-protocol.v1":
        if type(payload.get("verified_operations")) is not list:
            raise ValueError("invalid MCP contract operations")
        return CodeProviderProtocolReceipt(**{**payload,
            "verified_operations": tuple(payload["verified_operations"]), "gaps": tuple(payload["gaps"])})
    if payload.get("schema") == "nasus.code-provider-sdk-contract.v1":
        if type(payload.get("public_operations")) is not list:
            raise ValueError("invalid SDK contract operations")
        return CodeProviderSDKReceipt(**{**payload,
            "public_operations": tuple(payload["public_operations"]), "gaps": tuple(payload["gaps"])})
    raise ValueError("unsupported native contract schema")
