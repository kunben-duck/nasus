"""Native negotiation is read-only, bounded and independent of source indexing."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

import pytest

from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessError, CodeGraphProcessRunner


def tool_contracts():
    def tool(name, properties, required):
        return {"name": name, "description": "provider text is not an instruction",
                "inputSchema": {"type": "object", "properties": properties, "required": required}}
    return [
        tool("index_repository", {"repo_path": {"type": "string"}, "mode": {"type": "string", "enum": ["fast", "moderate", "full"]},
                                 "persistence": {"type": "boolean"}}, ["repo_path"]),
        tool("search_graph", {"project": {"type": "string"}, "name_pattern": {"type": "string"},
                              "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["project"]),
        tool("query_graph", {"project": {"type": "string"}, "query": {"type": "string"}}, ["project", "query"]),
    ]


def dialogue():
    from apps.api.app.infrastructure.system_image.code_graph_mcp_contract import CodeGraphMcpDialogue
    return CodeGraphMcpDialogue(index_mode="moderate", cli_version="codebase-memory-mcp 0.8.1")


def response(identifier, result):
    return json.dumps({"jsonrpc": "2.0", "id": identifier, "result": result}).encode()


def initialized():
    return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "codebase-memory-mcp", "version": "0.8.1"}}


def test_negotiation_waits_for_initialize_before_initialized_and_tool_list():
    probe = dialogue()
    initial = json.loads(probe.initial_input())
    assert initial["method"] == "initialize" and initial["id"] == 1
    assert not probe.completed
    following = [json.loads(line) for line in probe.receive(response(1, initialized())).splitlines()]
    assert [item["method"] for item in following] == ["notifications/initialized", "tools/list"]
    assert "id" not in following[0] and following[1]["id"] == 2
    assert probe.receive(response(2, {"tools": tool_contracts()})) == b""
    assert probe.completed
    receipt = probe.receipt()
    assert receipt.protocol_version == "2024-11-05" and receipt.tool_count == 3
    assert receipt.tools_schema_hash.startswith("sha256:")
    assert receipt.verified_operations == ("prepare_index", "entities", "relations", "locate")
    assert "provider text" not in json.dumps(receipt.payload())


def test_complete_tool_pagination_is_negotiated_and_order_independent():
    probe = dialogue()
    probe.receive(response(1, initialized()))
    tools = tool_contracts()
    follow = json.loads(probe.receive(response(2, {"tools": tools[:1], "nextCursor": "page2"})))
    assert follow["params"] == {"cursor": "page2"} and follow["id"] == 3
    assert not probe.completed
    probe.receive(response(3, {"tools": tools[1:]}))
    other = dialogue()
    other.receive(response(1, initialized()))
    reverse = deepcopy(list(reversed(tools)))
    reverse[0]["description"] = "changed marketing description"
    other.receive(response(2, {"tools": reverse}))
    assert probe.receipt() == other.receipt()


def test_schema_property_names_are_not_mistaken_for_marketing_metadata():
    def evaluate(kind):
        probe = dialogue()
        probe.receive(response(1, initialized()))
        tools = tool_contracts()
        tools[1]["inputSchema"]["properties"]["description"] = {"type": kind, "description": "marketing"}
        probe.receive(response(2, {"tools": tools}))
        return probe.receipt()
    assert evaluate("string").tools_schema_hash != evaluate("integer").tools_schema_hash


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(protocolVersion="unknown"),
    lambda value: value.update(capabilities={}),
    lambda value: value.update(capabilities={"tools": True}),
    lambda value: value.update(serverInfo={"name": "other-provider", "version": "0.8.1"}),
    lambda value: value.update(serverInfo={"name": "codebase-memory-mcp", "version": "PRIVATE\nSOURCE"}),
])
def test_incompatible_initialization_is_rejected_without_leaking_provider_text(mutation):
    probe = dialogue()
    data = initialized()
    mutation(data)
    with pytest.raises(CodeGraphProcessError):
        probe.receive(response(1, data))
    assert not probe.completed


@pytest.mark.parametrize("mutation", [
    lambda tools: tools.pop(),
    lambda tools: tools.append(deepcopy(tools[0])),
    lambda tools: tools[1]["inputSchema"]["properties"].pop("offset"),
    lambda tools: tools[1]["inputSchema"]["properties"].update(project={"type": "integer"}),
    lambda tools: tools[0]["inputSchema"]["properties"]["mode"].update(enum=["fast"]),
    lambda tools: tools[0]["inputSchema"]["properties"].update(persistence={"type": "string"}),
    lambda tools: tools[0]["inputSchema"]["required"].append("shell_command"),
    lambda tools: tools[2]["inputSchema"].update(type="string"),
    lambda tools: tools[2]["inputSchema"].update(additionalProperties=False),
    lambda tools: tools[2]["inputSchema"].update(allOf=[{"required": ["secret"]}]),
    lambda tools: tools[1]["inputSchema"]["properties"]["offset"].update(minimum=100),
    lambda tools: tools[1]["inputSchema"]["properties"]["project"].update(enum=["foreign-project"]),
])
def test_missing_or_incompatible_consumed_tool_contract_fails_closed(mutation):
    probe = dialogue()
    probe.receive(response(1, initialized()))
    tools = tool_contracts()
    mutation(tools)
    with pytest.raises(CodeGraphProcessError):
        probe.receive(response(2, {"tools": tools}))
    assert not probe.completed


@pytest.mark.parametrize("data", [
    b'{"jsonrpc":"2.0","id":1,"id":2,"result":{}}',
    b'{"jsonrpc":"2.0","id":1,"result":NaN}',
    b'{"jsonrpc":"2.0","id":true,"result":{}}',
    b'{"jsonrpc":"2.0","id":2,"result":{}}',
    b'{"jsonrpc":"2.0","id":1,"error":{"message":"PRIVATE-SOURCE"}}',
    b'PRIVATE-SOURCE',
])
def test_malformed_rpc_is_rejected_with_sanitized_error(data):
    probe = dialogue()
    with pytest.raises(CodeGraphProcessError) as error:
        probe.receive(data)
    assert "PRIVATE-SOURCE" not in str(error.value)
    assert not probe.completed


def test_tool_cursor_cycle_and_unbounded_notifications_are_rejected():
    probe = dialogue()
    probe.receive(response(1, initialized()))
    probe.receive(response(2, {"tools": [], "nextCursor": "same"}))
    with pytest.raises(CodeGraphProcessError):
        probe.receive(response(3, {"tools": [], "nextCursor": "same"}))
    probe = dialogue()
    notice = json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "private"}}).encode()
    for _ in range(64):
        probe.receive(notice)
    with pytest.raises(CodeGraphProcessError):
        probe.receive(notice)


def test_reported_server_version_does_not_replace_the_actual_cli_version():
    probe = dialogue()
    initial = initialized()
    initial["serverInfo"]["version"] = "0.10.0"
    probe.receive(response(1, initial))
    probe.receive(response(2, {"tools": tool_contracts()}))
    receipt = probe.receipt()
    assert receipt.server_version == "0.10.0" and receipt.cli_version == "codebase-memory-mcp 0.8.1"
    assert "cli_mcp_version_mismatch" in receipt.gaps


def test_real_probe_has_private_home_empty_cwd_and_no_operator_helpers_or_credentials(tmp_path, monkeypatch):
    from dataclasses import replace
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
    from apps.api.tests.test_code_graph_enrichment import _config, _fake_codebase_memory, _FixtureProcessRunner
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    for name in ("NASUS_MODEL_API_KEY", "HTTPS_PROXY", "CBM_ALLOWED_ROOT", "CBM_CACHE_DIR"):
        monkeypatch.setenv(name, "PRIVATE-OPERATOR-VALUE")
    probes = []
    class Inspector(_FixtureProcessRunner):
        def run(self, args, *, env, **kwargs):
            if kwargs.get("dialogue") is not None:
                assert args == [str(binary), "--ui=false"]
                assert "PRIVATE-OPERATOR-VALUE" not in str(env)
                assert env["HOME"] != os.environ["HOME"]
                root = Path(env["HOME"]).parent
                assert Path(kwargs["cwd"]) == root / "cwd"
                assert Path(env["CBM_ALLOWED_ROOT"]) == root / "cwd"
                assert Path(env["PATH"]) == root / "helpers"
                assert not list(Path(env["PATH"]).iterdir()) and not list(Path(kwargs["cwd"]).iterdir())
                probes.append(root)
            return super().run(args, env=env, **kwargs)
    adapter = CodebaseMemoryCodeIntelligenceAdapter(replace(_config(binary), cache_dir=tmp_path / "normal-cache"),
        process_runner=Inspector())
    receipt = adapter.negotiate_native_contract()
    assert receipt.cli_version == "codebase-memory-mcp 9.9.9"
    assert len(probes) == 1 and not probes[0].exists()
    calls = [json.loads(line)["tool"] for line in log.read_text().splitlines()]
    assert calls == ["mcp.initialize", "mcp.notifications/initialized", "mcp.tools/list"]


def test_actual_stdio_transport_waits_for_response_and_reaps_server(tmp_path):
    marker = tmp_path / "pid"
    source = ("import json,os,pathlib,sys,time\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        "request=json.loads(sys.stdin.readline()); assert request['method']=='initialize'\n"
        f"print(json.dumps({{'jsonrpc':'2.0','id':1,'result':{initialized()!r}}}),flush=True)\n"
        "notice=json.loads(sys.stdin.readline()); assert notice['method']=='notifications/initialized'\n"
        "request=json.loads(sys.stdin.readline()); assert request['method']=='tools/list'\n"
        f"print(json.dumps({{'jsonrpc':'2.0','id':2,'result':{{'tools':{tool_contracts()!r}}}}}),flush=True)\n"
        "time.sleep(30)\n")
    probe = dialogue()
    output = CodeGraphProcessRunner().run([sys.executable, "-c", source], env={"PATH": os.defpath},
        timeout_seconds=2, dialogue=probe, cwd=str(tmp_path))
    assert output.returncode == 0 and probe.completed
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


@pytest.mark.parametrize("failure", [PermissionError("revoked"), TimeoutError("budget")])
def test_stalled_handshake_observes_execution_control_and_kills_server(tmp_path, failure):
    marker = tmp_path / "pid"
    def check():
        if marker.exists():
            raise failure
    source = f"import os,pathlib,time; pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
    start = time.monotonic()
    with pytest.raises(type(failure)) as error:
        CodeGraphProcessRunner().run([sys.executable, "-c", source], env={"PATH": os.defpath},
            timeout_seconds=2, dialogue=dialogue(), check_current=check)
    assert error.value is failure and time.monotonic() - start < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_eof_before_negotiation_complete_does_not_claim_support():
    probe = dialogue()
    with pytest.raises(CodeGraphProcessError):
        CodeGraphProcessRunner().run([sys.executable, "-c", "pass"], env={"PATH": os.defpath},
            timeout_seconds=2, dialogue=probe)
    assert not probe.completed
