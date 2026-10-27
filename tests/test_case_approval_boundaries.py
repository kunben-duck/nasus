import ast
from pathlib import Path

from tests.test_automation_script_boundaries import imports, ROOT


def test_case_admission_domain_and_application_use_only_domain_ports():
    for path in (ROOT / "domain/quality_loop/case_approval.py", ROOT / "domain/quality_loop/automation_case_admission.py",
                 ROOT / "application/quality_loop/case_approvals.py"):
        modules = tuple(imports(path))
        assert not any(any(part in module.split(".") for part in
            ("sqlalchemy", "infrastructure", "fastapi", "langgraph", "temporalio", "httpx", "boto3", "store")) for module in modules)


def test_case_admission_http_is_read_only_and_does_not_bypass_canonical_tools():
    tree = ast.parse((ROOT / "interface/http/routers/case_approvals.py").read_text())
    methods = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "router"]
    assert methods == ["get", "get"]
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"review", "record", "commit", "execute"} for node in ast.walk(tree))


def test_case_admission_is_explicitly_confirmed_and_has_a_separate_resource_policy():
    from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
    from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_TOOL
    tools = {tool.tool_id: tool for tool in core_tool_definitions() + system_image_tool_definitions()}
    assert tools[CASE_APPROVAL_TOOL].confirmation_mode == "user_confirm"
    assert tools[CASE_APPROVAL_TOOL].tool_kind == "governance"
    assembly = (ROOT / "store.py").read_text()
    assert "CaseApprovalInvocationResourcePolicy(" in assembly and "case_approvals=self.case_approvals" in assembly
    models = (ROOT / "infrastructure/persistence/db_models.py").read_text()
    assert "from .case_approval_models import" in models


def test_new_script_generation_consumes_case_admission_through_an_application_port():
    script = (ROOT / "application/quality_loop/automation_script_generation.py").read_text()
    assert "class AutomationCaseAdmissionPort(Protocol)" in script
    assert "admission = self._admission(selection, prepared)" in script
    assert "self._admission(request, prepared, historical=True)" in script
    assert "self._admission(request, live_input)" in script
    assert "admissions=self.case_approvals" in (ROOT / "store.py").read_text()
    migration = (ROOT.parent / "migrations/versions/0122_automation_case_admission.py").read_text()
    assert 'down_revision = "0121_case_approvals"' in migration
    assert '"fk_automation_case_admission"' in migration and '"ck_automation_case_admission_pair"' in migration
    assert "UPDATE " not in migration and "Cannot discard populated" in migration
