"""Cloudflare Turnstile on the login (wiki: "Servicios de terceros").

Cloudflare is the only thing replaced: `fake_siteverify` is an
`httpx.MockTransport` that answers like `siteverify` does with Cloudflare's
published test secrets, so the suite runs offline and in CI. Everything from the
endpoint to the HTTP request is the real code.
"""

import json
import logging
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.config import settings
from models.login_attempt_model import LoginAttempt
from services import turnstile_service
from services.turnstile_service import verify_turnstile
from tests.conftest import DEFAULT_PASSWORD, LOGIN_URL

EMAIL = "admin.a@demo.mx"
PASSING_SECRET = "1x0000000000000000000000000000000AA"
FAILING_SECRET = "2x0000000000000000000000000000000AA"
TOKEN = "XXXX.DUMMY.TOKEN.XXXX"


class FakeSiteverify:
    """Answers like Cloudflare's siteverify and keeps every request it got."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handler: Callable[[httpx.Request], httpx.Response] = self.cloudflare

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @staticmethod
    def form(request: httpx.Request) -> dict[str, list[str]]:
        return parse_qs(request.content.decode())

    def cloudflare(self, request: httpx.Request) -> httpx.Response:
        secret = self.form(request).get("secret", [""])[0]
        if secret == PASSING_SECRET:
            body = {"success": True, "hostname": settings.turnstile_hostname, "error-codes": []}
        elif secret == FAILING_SECRET:
            body = {"success": False, "error-codes": ["invalid-input-response"]}
        else:
            body = {"success": False, "error-codes": ["invalid-input-secret"]}
        return httpx.Response(200, json=body)


@pytest.fixture
def siteverify(monkeypatch: pytest.MonkeyPatch) -> FakeSiteverify:
    fake = FakeSiteverify()
    monkeypatch.setattr(turnstile_service, "_transport", httpx.MockTransport(fake))
    return fake


@pytest.fixture
def turnstile_on(monkeypatch: pytest.MonkeyPatch, siteverify: FakeSiteverify) -> FakeSiteverify:
    """Flag on, with the test secret that always passes."""
    monkeypatch.setattr(settings, "turnstile_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret", PASSING_SECRET)
    return siteverify


def use_secret(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    monkeypatch.setattr(settings, "turnstile_secret", secret)


def post_login(
    client: TestClient, token: str | None = TOKEN, password: str = DEFAULT_PASSWORD
) -> httpx.Response:
    headers = {"X-Turnstile-Token": token} if token is not None else {}
    return client.post(LOGIN_URL, data={"username": EMAIL, "password": password}, headers=headers)


def attempts(session: Session) -> list[LoginAttempt]:
    session.expire_all()
    return list(session.exec(select(LoginAttempt)).all())


class TestFlagOff:
    def test_header_is_ignored(
        self, client: TestClient, two_businesses, siteverify: FakeSiteverify
    ) -> None:
        assert post_login(client, token="garbage").status_code == 200
        assert siteverify.requests == []

    def test_login_without_header_works_as_before(
        self, client: TestClient, two_businesses, siteverify: FakeSiteverify
    ) -> None:
        assert post_login(client, token=None).status_code == 200
        assert siteverify.requests == []


class TestFlagOn:
    def test_passing_secret_logs_in(
        self, client: TestClient, two_businesses, turnstile_on: FakeSiteverify
    ) -> None:
        response = post_login(client)
        assert response.status_code == 200
        assert settings.cookie_name in response.cookies
        assert len(turnstile_on.requests) == 1

    def test_failing_secret_is_400(
        self, client: TestClient, two_businesses, turnstile_on, monkeypatch
    ) -> None:
        use_secret(monkeypatch, FAILING_SECRET)
        response = post_login(client)
        assert response.status_code == 400
        assert response.json() == {"detail": "turnstile_failed", "code": "turnstile_failed"}
        assert "set-cookie" not in response.headers

    def test_missing_header_is_400_without_calling_cloudflare(
        self, client: TestClient, two_businesses, turnstile_on: FakeSiteverify
    ) -> None:
        response = post_login(client, token=None)
        assert response.status_code == 400
        assert response.json()["code"] == "turnstile_failed"
        assert turnstile_on.requests == []

    def test_empty_header_is_400(
        self, client: TestClient, two_businesses, turnstile_on: FakeSiteverify
    ) -> None:
        assert post_login(client, token="").status_code == 400
        assert turnstile_on.requests == []

    def test_wrong_password_with_valid_token_is_still_401(
        self, client: TestClient, two_businesses, turnstile_on
    ) -> None:
        response = post_login(client, password="wrong")
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    def test_siteverify_timeout_is_400(
        self, client: TestClient, two_businesses, turnstile_on: FakeSiteverify
    ) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("siteverify is slow", request=request)

        turnstile_on.handler = timeout
        response = post_login(client)
        assert response.status_code == 400
        assert response.json()["code"] == "turnstile_failed"


class TestOrder:
    """Turnstile → H4 lock → credentials."""

    def test_turnstile_failure_does_not_count_login_attempts(
        self, client: TestClient, session: Session, two_businesses, turnstile_on, monkeypatch
    ) -> None:
        use_secret(monkeypatch, FAILING_SECRET)
        statuses = [post_login(client, password="wrong").status_code for _ in range(10)]
        assert statuses == [400] * 10
        assert attempts(session) == []

        use_secret(monkeypatch, PASSING_SECRET)
        assert post_login(client).status_code == 200

    def test_turnstile_is_checked_before_the_lock(
        self, client: TestClient, two_businesses, turnstile_on, monkeypatch
    ) -> None:
        for _ in range(settings.login_max_attempts):
            post_login(client, password="wrong")
        assert post_login(client).status_code == 429

        use_secret(monkeypatch, FAILING_SECRET)
        assert post_login(client).status_code == 400


class TestSiteverifyRequest:
    def test_sends_secret_and_token_without_remoteip(self, turnstile_on: FakeSiteverify) -> None:
        assert verify_turnstile(TOKEN) is True
        request = turnstile_on.requests[0]
        assert request.method == "POST"
        assert str(request.url) == settings.turnstile_siteverify_url
        assert FakeSiteverify.form(request) == {"secret": [PASSING_SECRET], "response": [TOKEN]}

    def test_uses_a_5_second_timeout(self, turnstile_on: FakeSiteverify) -> None:
        verify_turnstile(TOKEN)
        timeouts = turnstile_on.requests[0].extensions["timeout"]
        assert set(timeouts.values()) == {5.0}

    def test_flag_off_never_touches_the_network(self, siteverify: FakeSiteverify) -> None:
        assert settings.turnstile_enabled is False
        assert verify_turnstile(None) is True
        assert siteverify.requests == []

    def test_oversized_token_is_rejected_locally(self, turnstile_on: FakeSiteverify) -> None:
        assert verify_turnstile("x" * (turnstile_service.MAX_TOKEN_LENGTH + 1)) is False
        assert turnstile_on.requests == []


class TestSiteverifyAnswers:
    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500, json={"success": True}),
            httpx.Response(200, content=b"<html>not json</html>"),
            httpx.Response(200, json=["success"]),
            httpx.Response(200, json={"success": "true", "hostname": "localhost"}),
            httpx.Response(200, json={"error-codes": []}),
        ],
        ids=["server-error", "not-json", "not-an-object", "success-as-string", "no-success"],
    )
    def test_unexpected_answers_fail_closed(
        self, turnstile_on: FakeSiteverify, response: httpx.Response
    ) -> None:
        turnstile_on.handler = lambda request: response
        assert verify_turnstile(TOKEN) is False

    def test_connection_error_fails_closed(self, turnstile_on: FakeSiteverify) -> None:
        def offline(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no internet", request=request)

        turnstile_on.handler = offline
        assert verify_turnstile(TOKEN) is False

    def test_token_solved_on_another_hostname_fails(self, turnstile_on: FakeSiteverify) -> None:
        turnstile_on.handler = lambda request: httpx.Response(
            200, json={"success": True, "hostname": "evil.example"}
        )
        assert verify_turnstile(TOKEN) is False

    def test_logs_error_codes_but_never_the_secret(
        self, turnstile_on, monkeypatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        use_secret(monkeypatch, FAILING_SECRET)
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            assert verify_turnstile(TOKEN) is False
        assert "invalid-input-response" in caplog.text
        assert FAILING_SECRET not in caplog.text
        assert json.dumps(FAILING_SECRET) not in caplog.text
