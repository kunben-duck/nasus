"""Only initialize and enumerate tools; never execute provider instructions."""
import json
import re

from ...domain.system_image.code_provider_protocol import CodeProviderProtocolReceipt
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_graph_process import CodeGraphProcessError


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate protocol field")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("invalid protocol number")


def _line(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def _schema_contract(value, *, property_names=False):
    if type(value) is dict:
        return {key: (item if not property_names and key in {"default", "const", "enum"} else
                      _schema_contract(item, property_names=not property_names and key in {"properties", "$defs", "definitions"}))
                for key, item in value.items() if property_names or key not in {"description", "$comment", "title", "examples"}}
    if type(value) is list:
        return [_schema_contract(item) for item in value]
    return value


class CodeGraphMcpDialogue:
    def __init__(self, *, index_mode, cli_version):
        if index_mode not in {"fast", "moderate", "full"}:
            raise ValueError("unsupported static code index mode")
        self.index_mode = index_mode
        self.cli_version = cli_version
        self.completed, self._expected_id, self._phase = False, 1, "initialize"
        self._notifications, self._pages, self._tools, self._cursors = 0, 0, {}, set()
        self._server, self._receipt = None, None

    def initial_input(self):
        return _line({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "nasus-code-contract-probe", "version": "1"}}})

    def receive(self, line):
        try:
            return self._receive(line)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            raise CodeGraphProcessError("code graph native contract is incompatible") from error

    def _receive(self, line):
        if self.completed or type(line) is not bytes or len(line) > 512 * 1024:
            raise ValueError("invalid native response size or phase")
        value = json.loads(line, object_pairs_hook=_json_object, parse_constant=_invalid_constant)
        if type(value) is not dict or value.get("jsonrpc") != "2.0":
            raise ValueError("invalid native protocol envelope")
        if "method" in value:
            if ("id" in value or value["method"] != "notifications/message" or type(value.get("params")) is not dict):
                raise ValueError("unsupported provider request")
            self._notifications += 1
            if self._notifications > 64:
                raise ValueError("native notification budget exceeded")
            return b""
        if (type(value.get("id")) is not int or value["id"] != self._expected_id
                or "error" in value or type(value.get("result")) is not dict):
            raise ValueError("invalid native response correlation")
        result = value["result"]
        if self._phase == "initialize":
            server = result.get("serverInfo")
            capabilities = result.get("capabilities")
            if (result.get("protocolVersion") not in {"2024-11-05", "2025-03-26", "2025-06-18"}
                    or type(server) is not dict or server.get("name") != "codebase-memory-mcp"
                    or type(server.get("version")) is not str
                    or re.fullmatch(r"[a-zA-Z0-9_.+()-]{1,120}", server["version"]) is None
                    or type(capabilities) is not dict or type(capabilities.get("tools")) is not dict):
                raise ValueError("unsupported native initialization")
            self._server = (result["protocolVersion"], server["name"], server["version"])
            self._phase, self._expected_id = "tools", 2
            return _line({"jsonrpc": "2.0", "method": "notifications/initialized"}) + self._request_tools()
        tools = result.get("tools")
        if type(tools) is not list or len(tools) > 128:
            raise ValueError("invalid native tool inventory")
        self._pages += 1
        if self._pages > 8:
            raise ValueError("native tool inventory page budget exceeded")
        for tool in tools:
            if (type(tool) is not dict or type(tool.get("name")) is not str
                    or re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", tool["name"]) is None
                    or tool["name"] in self._tools or type(tool.get("inputSchema")) is not dict):
                raise ValueError("invalid or repeated native tool")
            self._tools[tool["name"]] = _schema_contract(tool["inputSchema"])
            if len(self._tools) > 128:
                raise ValueError("native tool inventory exceeded its budget")
        if "nextCursor" in result:
            cursor = result["nextCursor"]
            if type(cursor) is not str or not 1 <= len(cursor) <= 2048 or cursor in self._cursors:
                raise ValueError("invalid native inventory cursor")
            self._cursors.add(cursor)
            self._expected_id += 1
            return self._request_tools(cursor)
        self._validate_consumed_contracts()
        protocol, name, version = self._server
        gaps = []
        if "name" not in self._tools["index_repository"]["properties"]:
            gaps.append("native_namespace_parameter_not_advertised")
        if "format" not in self._tools["query_graph"]["properties"]:
            gaps.append("native_query_format_not_advertised")
        if self.cli_version.rsplit(" ", 1)[-1] != version:
            gaps.append("cli_mcp_version_mismatch")
        self._receipt = CodeProviderProtocolReceipt("codebase-memory", protocol, name, version, self.cli_version,
            snapshot_digest({key: self._tools[key] for key in sorted(self._tools)}), len(self._tools),
            ("prepare_index", "entities", "relations", "locate"), tuple(gaps))
        self.completed = True
        return b""

    def _request_tools(self, cursor=None):
        return _line({"jsonrpc": "2.0", "id": self._expected_id, "method": "tools/list",
                      "params": {} if cursor is None else {"cursor": cursor}})

    def _validate_consumed_contracts(self):
        consumed = {
            "index_repository": {"repo_path": "string", "mode": "string", "persistence": "boolean"},
            "search_graph": {"project": "string", "name_pattern": "string", "offset": "integer", "limit": "integer"},
            "query_graph": {"project": "string", "query": "string"},
        }
        sent_fields = {"index_repository": {"repo_path", "mode", "persistence", "name"},
                       "search_graph": set(consumed["search_graph"]), "query_graph": {"project", "query", "format"}}
        for tool, fields in consumed.items():
            schema = self._tools.get(tool)
            if type(schema) is not dict or schema.get("type") != "object" or type(schema.get("properties")) is not dict:
                raise ValueError("required native tool is not available")
            if set(schema) - {"type", "properties", "required", "additionalProperties", "$schema"}:
                raise ValueError("unsupported native schema constraints")
            required = schema.get("required", [])
            if (type(required) is not list or any(type(key) is not str for key in required)
                    or len(set(required)) != len(required) or not set(required) <= sent_fields[tool]):
                raise ValueError("native tool requires unsupported arguments")
            for name, kind in fields.items():
                field = schema["properties"].get(name)
                if (type(field) is not dict or field.get("type") != kind
                        or set(field) - {"type", "default", "enum"}
                        or ("enum" in field and not (tool == "index_repository" and name == "mode"))):
                    raise ValueError("native argument contract is incompatible")
            if schema.get("additionalProperties", True) is not True:
                if (schema["additionalProperties"] is not False
                        or not sent_fields[tool] <= set(schema["properties"])):
                    raise ValueError("native contract rejects sent extension arguments")
            for name in sent_fields[tool] - fields.keys():
                if name in schema["properties"] and schema["properties"][name] != {"type": "string"}:
                    raise ValueError("unsupported native extension argument constraints")
            if tool == "index_repository":
                modes = schema["properties"]["mode"].get("enum")
                if type(modes) is not list or self.index_mode not in modes:
                    raise ValueError("native static index mode is not supported")

    def receipt(self):
        if not self.completed or self._receipt is None:
            raise CodeGraphProcessError("code graph native negotiation is not complete")
        return self._receipt
