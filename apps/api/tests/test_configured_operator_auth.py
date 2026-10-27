import json
from dataclasses import replace

import pytest
from starlette.requests import Request

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.interface.http.auth import AuthConfig, authenticate_request


CONFIG = AuthConfig(mode="required", bearer_token="static-token", user_id="operator",
    user_name="Configured", user_email="operator@example.test", user_role="platform_admin")


def request(path="/v1/auth/me", *, token="static-token", query=False):
    return Request({"type": "http", "method": "GET", "path": path,
        "headers": [(b"authorization", ("Bearer " + token).encode())] if token and not query else [],
        "query_string": ("access_token=" + token).encode() if token and query else b""})


@pytest.mark.parametrize("configuration,token", [(CONFIG, "static-token"), (replace(CONFIG, mode="dev"), "")])
def test_protected_configured_identity_requires_a_verifier(configuration, token):
    response = authenticate_request(request(token=token), configuration)
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "configured_identity_verifier_unavailable"


@pytest.mark.parametrize("unavailable", [None,
    UserProfile(id="other", email=CONFIG.user_email, name="Wrong identity", role="platform_admin"),
    UserProfile(id=CONFIG.user_id, email="other@example.test", name="Wrong email", role="platform_admin")])
def test_missing_or_mismatched_identity_is_rejected(unavailable):
    response = authenticate_request(request(), CONFIG, configured_identity_authenticator=lambda _: unavailable)
    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "configured_identity_unavailable"


def test_lookup_failure_is_redacted_and_never_falls_back_to_configured_privileges():
    def fail(_):
        raise RuntimeError("secret database URI and static-token")
    response = authenticate_request(request(), CONFIG, configured_identity_authenticator=fail)
    assert response.status_code == 503
    assert b"secret" not in response.body and b"static-token" not in response.body


@pytest.mark.parametrize("query", [False, True])
def test_current_role_and_profile_are_used_for_header_and_query_tokens(query):
    current = CONFIG.user().model_copy(update={"role": "viewer", "name": "Current name", "avatar_preset": "yellow_duck"})
    assert authenticate_request(request(query=query), CONFIG,
        configured_identity_authenticator=lambda _: current) == current


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/v1/auth/register", "/v1/auth/login"])
def test_public_requests_do_not_require_configured_identity_verification(path):
    def unexpected(_):
        raise AssertionError("public request must not verify a configured identity")
    assert authenticate_request(request(path), CONFIG, configured_identity_authenticator=unexpected) == CONFIG.user()


def test_real_session_identity_is_not_replaced_by_the_configured_operator():
    session = UserProfile(id="registered_user", email="registered@example.test", name="Person", role="tester")
    def unexpected(_):
        raise AssertionError("registered session must not use operator identity")
    assert authenticate_request(request(token="session-token"), CONFIG,
        token_authenticator=lambda _: session, configured_identity_authenticator=unexpected) == session
