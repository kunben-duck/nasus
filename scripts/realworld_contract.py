"""Independent US-001 acceptance oracle; never derive expectations from target output."""
import json
from uuid import uuid4


CASES = ("author_edit", "partial_edit", "title_slug", "anonymous_denied", "other_author_denied", "missing_article")
HTTP_CLIENT = '''import json, sys, urllib.request, urllib.error
p = json.load(sys.stdin)
headers = {"Content-Type": "application/json"}
if p.get("token"): headers["Authorization"] = "Token " + p["token"]
req = urllib.request.Request("http://127.0.0.1:8080" + p["path"],
    data=json.dumps(p["body"]).encode() if p.get("body") is not None else None,
    headers=headers, method=p["method"])
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        status, raw = response.status, response.read(65537)
except urllib.error.HTTPError as response:
    status, raw = response.code, response.read(65537)
assert len(raw) <= 65536
try: body = json.loads(raw) if raw else None
except ValueError: body = {"non_json_response": True}
print(json.dumps({"status": status, "body": body}))
'''


def redact(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if key.lower() in {"password", "token", "authorization"} else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def evaluate(case_id, update, before, after):
    """Return individual assertions, including persistence and forbidden-write checks."""
    status = 401 if case_id == "anonymous_denied" else 403 if case_id == "other_author_denied" else 404 if case_id == "missing_article" else 200
    assertions = [{"name": "status", "expected": status, "actual": update["status"], "passed": update["status"] == status}]
    article = (after.get("body") or {}).get("article", {})
    if case_id in {"anonymous_denied", "other_author_denied", "missing_article"}:
        expected = {key: before[key] for key in ("title", "description", "body", "slug", "author")}
        actual = {key: article.get(key) for key in expected}
        assertions.append({"name": "no_forbidden_write", "expected": expected, "actual": actual, "passed": actual == expected})
    else:
        expected = {key: before[key] for key in ("title", "description", "body", "author")}
        if case_id == "title_slug":
            expected["title"] = "updated " + before["title"]
        else:
            expected.update(body="updated body", slug=before["slug"])
        if case_id == "author_edit":
            expected["description"] = "updated description"
        actual = {key: article.get(key) for key in expected}
        assertions.append({"name": "persisted_fields", "expected": expected, "actual": actual,
                           "passed": after["status"] == 200 and actual == expected})
        if case_id == "title_slug":
            slug = article.get("slug")
            assertions.append({"name": "slug_changes_with_title", "expected": "nonempty different slug",
                "actual": slug, "passed": isinstance(slug, str) and bool(slug) and slug != before["slug"]})
    return assertions


def run_cases(command, container):
    results = []
    for case_id in CASES:
        evidence = []
        def request(method, path, body=None, token=None, phase="test"):
            payload = {"method": method, "path": path, "body": body, "token": token}
            code, raw = command(["docker", "exec", "-i", container, "python", "-c", HTTP_CLIENT],
                                timeout=20, max_bytes=256 * 1024, input_body=json.dumps(payload).encode())
            if code:
                raise RuntimeError("realworld_http_transport_failed")
            response = json.loads(raw)
            evidence.append({"phase": phase, "request": redact(payload), "response": redact(response)})
            return response
        def user(suffix):
            name = "nasus" + uuid4().hex[:16] + suffix
            response = request("POST", "/api/users", {"user": {"username": name,
                "email": name + "@example.com", "password": "Isolated-Test-Password-741!"}}, phase="setup")
            if response["status"] != 201:
                raise RuntimeError("realworld_user_setup_failed")
            return response["body"]["user"]["token"]
        result = {"case_id": case_id, "status": "setup_failed", "evidence": evidence, "cleanup": "environment_teardown"}
        slug, owner_token = None, None
        try:
            owner_token, other_token = user("a"), user("b")
            create = request("POST", "/api/articles", {"article": {"title": "Article " + uuid4().hex,
                "description": "original description", "body": "original body"}}, owner_token, "setup")
            if create["status"] != 201:
                raise RuntimeError("realworld_article_setup_failed")
            before = create["body"]["article"]
            slug = before["slug"]
            result["status"] = "execution_error"
            changes = {"body": "updated body"}
            if case_id == "author_edit": changes["description"] = "updated description"
            if case_id == "title_slug": changes = {"title": "updated " + before["title"]}
            token = None if case_id == "anonymous_denied" else other_token if case_id == "other_author_denied" else owner_token
            target = "missing-" + uuid4().hex if case_id == "missing_article" else slug
            update = request("PUT", "/api/articles/" + target, {"article": changes}, token)
            if case_id == "title_slug" and update["status"] == 200:
                slug = update["body"]["article"]["slug"]
            after = request("GET", "/api/articles/" + slug)
            assertions = evaluate(case_id, update, before, after)
            result.update(status="passed" if all(a["passed"] for a in assertions) else "failed", assertions=assertions)
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            if slug and owner_token:
                try:
                    cleanup = request("DELETE", "/api/articles/" + slug, token=owner_token, phase="cleanup")
                    absent = request("GET", "/api/articles/" + slug, phase="cleanup")
                    result["cleanup"] = "article_removed" if cleanup["status"] == 204 and absent["status"] == 404 else "failed"
                except (RuntimeError, ValueError, KeyError):
                    result["cleanup"] = "failed"
        results.append(result)
    return results
