"""Frozen Django route proof: no imports, execution or inferred business oracles."""
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.tests.test_http_locator_uncertainty import scoped_plan
from apps.api.tests.test_run_plan_locators import inventory_for


URLS = b'''from django.urls import path
from ninja import NinjaAPI
api_prefix = "api"
api = NinjaAPI()
api.add_router(f"/{api_prefix}", "articles.api.router")
api.add_router("/auth", "external_auth.api.router")
urlpatterns = [path("", api.urls)]
'''
ARTICLES = b'''from ninja import Router
router = Router()
@router.put("/articles/{slug}", auth=object(), response={200: dict})
def update(request, slug: str):
    raise RuntimeError("Source must never execute")
'''


def plan_for(path="/api/articles/{{session}}"):
    plan = scoped_plan(path, "PUT")
    plan["selection"]["target_build"].update(runtime="python", runtime_version="3.12")
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    return plan


def report(bodies=None, path="/api/articles/{{session}}"):
    plan = plan_for(path)
    port, _, _ = inventory_for(plan, bodies=bodies or {"config/urls.py": URLS, "apps/articles/api.py": ARTICLES})
    inventory = port.inspect(plan, require_access=lambda: None)
    return compile_http_locator_evidence(plan, inventory), plan, port


def test_literal_mount_import_and_fstring_have_cross_file_provenance():
    value, plan, port = report()
    assert value["summary"]["static_match"] == value["summary"]["locator_count"]
    route = value["locators"][0]["candidates"][0]
    assert route["route_path"] == "/api/articles/{slug}"
    assert {span["relative_path"] for span in route["supporting_spans"]} == {"config/urls.py", "apps/articles/api.py"}
    assert value["inventory"]["provider"] == "python-ast-django-ninja"
    assert value["schema"] == "nasus.run-plan-http-locators.v3"
    assert not value["runtime_locators_verified"] and not value["execution_authorized"]
    port.verify(plan, value["inventory"], require_access=lambda: None)
    bad = deepcopy(value["inventory"])
    bad["sources"][0]["routes"][0]["supporting_spans"][0]["snippet_hash"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="span"):
        port.verify(plan, bad, require_access=lambda: None)


@pytest.mark.parametrize("urls,article", [
    (URLS.replace(b'api_prefix = "api"', b'api_prefix = get_prefix()'), ARTICLES),
    (URLS.replace(b'api.add_router(f"/{api_prefix}", "articles.api.router")',
        b'if enabled:\n    api.add_router(f"/{api_prefix}", "articles.api.router")'), ARTICLES),
    (URLS, ARTICLES.replace(b'"/articles/{slug}"', b'get_path()')),
    (URLS, ARTICLES.replace(b'@router.put', b'@wrapper\n@router.put')),
    (URLS, ARTICLES + b'\nrouter = other_router\n'),
    (URLS.replace(b'urlpatterns = [path("", api.urls)]', b'urlpatterns = dynamic(api.urls)'), ARTICLES),
])
def test_dynamic_paths_conditional_mounts_and_shadowing_never_become_static_matches(urls, article):
    value, _, _ = report({"config/urls.py": urls, "apps/articles/api.py": article})
    assert value["summary"]["static_match"] == 0


def test_unresolved_external_mount_is_only_disjoint_for_literal_prefix():
    value, _, _ = report(path="/auth/tokens/refresh")
    assert value["summary"]["unresolved"] == value["summary"]["locator_count"]
    value, _, _ = report({"config/urls.py": URLS.replace(b'"/auth"', b'"/api"'), "apps/articles/api.py": ARTICLES})
    assert value["summary"]["unresolved"] == value["summary"]["locator_count"]


def test_failed_python_remains_unknown_and_duplicate_module_resolution_is_not_guessed():
    for extra in ({"broken.py": b"def broken("}, {"other/articles/api.py": ARTICLES}):
        value, _, _ = report({"config/urls.py": URLS, "apps/articles/api.py": ARTICLES, **extra})
        assert value["summary"]["static_match"] == 0


def test_empty_router_module_and_forward_constant_are_unresolved_without_crashing():
    value, _, _ = report({"config/urls.py": URLS, "apps/articles/api.py": b""})
    assert value["summary"]["unresolved"] == value["summary"]["locator_count"]
    urls = URLS.replace(b'api_prefix = "api"\n', b'') + b'api_prefix = "api"\n'
    value, _, _ = report({"config/urls.py": urls, "apps/articles/api.py": ARTICLES})
    assert value["summary"]["static_match"] == 0


def test_fixed_realworld_source_has_article_update_route_without_execution():
    root = Path(__file__).resolve().parents[3] / ".nasus/validation/realworld-django-ninja"
    if not (root / ".git").exists():
        pytest.skip("Optional fixed RealWorld checkout is not installed")
    sha = "87dd078c883a046f5ff20269df2fb004d8b5f83f"
    paths = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", "--name-only", sha]).decode().splitlines()
    bodies = {path: subprocess.check_output(["git", "-C", str(root), "show", sha + ":" + path])
        for path in paths if path.endswith(".py")}
    value, plan, port = report(bodies)
    assert value["summary"]["static_match"] == value["summary"]["locator_count"]
    port.verify(plan, value["inventory"], require_access=lambda: None)
