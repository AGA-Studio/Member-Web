"""System endpoints, OpenAPI schema and CORS."""

from fastapi.testclient import TestClient

EXPECTED_PATHS = {
    "/health",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/user/list",
    "/api/v1/user/create",
    "/api/v1/user/{user_id}",
    "/api/v1/user/{user_id}/update",
    "/api/v1/tier/list",
    "/api/v1/tier/{tier_id}/update",
    "/api/v1/customer/list",
    "/api/v1/customer/summary",
    "/api/v1/customer/lookup",
    "/api/v1/customer/create",
    "/api/v1/customer/{customer_id}",
    "/api/v1/customer/{customer_id}/update",
    "/api/v1/customer/{customer_id}/cancel",
    "/api/v1/checkout/preview",
    "/api/v1/checkout/create",
    "/api/v1/checkout/{checkout_id}",
    "/api/v1/movement/list",
    "/api/v1/movement/export",
}


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_ui_is_served(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_openapi_exposes_exactly_the_expected_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == EXPECTED_PATHS


def test_openapi_declares_password_flow_for_swagger_authorize(client: TestClient) -> None:
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/api/v1/auth/login"


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/does-not-exist").status_code == 404


class TestCors:
    def test_preflight_from_allowed_origin(self, client: TestClient) -> None:
        response = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        # Required for the browser to send the httpOnly cookie.
        assert response.headers["access-control-allow-credentials"] == "true"

    def test_preflight_from_unknown_origin_is_not_allowed(self, client: TestClient) -> None:
        response = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in response.headers

    def test_simple_request_from_allowed_origin(self, client: TestClient) -> None:
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
