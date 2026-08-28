"""🔐 Auth dependency tests — verifies X-User-* header extraction."""

from tests.conftest import AUTH_HEADERS


def should_authenticate_with_valid_headers(api_client):
    response = api_client.get("/api/v1/accounts", headers=AUTH_HEADERS)

    assert response.status_code == 200


def should_reject_missing_user_id(api_client):
    """Missing x-user-id header defaults to empty string → 401 Unauthorized."""
    headers = {k: v for k, v in AUTH_HEADERS.items() if k != "x-user-id"}

    response = api_client.get("/api/v1/accounts", headers=headers)

    assert response.status_code == 401


def should_accept_missing_user_name(api_client):
    """Missing x-user-name is non-critical metadata — request succeeds."""
    headers = {k: v for k, v in AUTH_HEADERS.items() if k != "x-user-name"}

    response = api_client.get("/api/v1/accounts", headers=headers)

    assert response.status_code == 200


def should_accept_missing_user_email(api_client):
    """Missing x-user-email is non-critical metadata — request succeeds."""
    headers = {k: v for k, v in AUTH_HEADERS.items() if k != "x-user-email"}

    response = api_client.get("/api/v1/accounts", headers=headers)

    assert response.status_code == 200


def should_reject_empty_user_id(api_client):
    """Header present but empty string triggers 401 from deps.py guard."""
    headers = {**AUTH_HEADERS, "x-user-id": ""}

    response = api_client.get("/api/v1/accounts", headers=headers)

    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


# ── Proxy secret validation (lines 32-39 of deps.py) ───────────────────────


class TestProxySecretValidation:
    """Tests for proxy secret enforcement when allow_insecure_proxy_secret=False."""

    @staticmethod
    def _make_settings(*, nuxt_proxy_secret: str = "test-secret"):
        """Build a Settings-like object with proxy secret enforcement enabled."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.local_mode = False  # Auth Mode — not Local Mode
        settings.allow_insecure_proxy_secret = False
        settings.nuxt_proxy_secret = nuxt_proxy_secret
        return settings

    def should_accept_correct_proxy_secret(self, api_client):
        """Request with correct x-proxy-secret header succeeds."""
        from unittest.mock import patch

        settings = self._make_settings(nuxt_proxy_secret="test-secret")
        headers = {**AUTH_HEADERS, "x-proxy-secret": "test-secret"}

        with patch("app.deps.get_settings", return_value=settings):
            response = api_client.get("/api/v1/accounts", headers=headers)

        assert response.status_code == 200

    def should_reject_missing_proxy_secret(self, api_client):
        """Request without x-proxy-secret header returns 401."""
        from unittest.mock import patch

        settings = self._make_settings(nuxt_proxy_secret="test-secret")

        with patch("app.deps.get_settings", return_value=settings):
            response = api_client.get("/api/v1/accounts", headers=AUTH_HEADERS)

        assert response.status_code == 401
        assert "Direct API access forbidden" in response.json()["detail"]

    def should_reject_wrong_proxy_secret(self, api_client):
        """Request with incorrect x-proxy-secret header returns 401."""
        from unittest.mock import patch

        settings = self._make_settings(nuxt_proxy_secret="test-secret")
        headers = {**AUTH_HEADERS, "x-proxy-secret": "wrong-secret"}

        with patch("app.deps.get_settings", return_value=settings):
            response = api_client.get("/api/v1/accounts", headers=headers)

        assert response.status_code == 401
        assert "Direct API access forbidden" in response.json()["detail"]

    def should_return_500_when_proxy_secret_not_configured(self, api_client):
        """When nuxt_proxy_secret is empty and insecure mode is off, returns 500."""
        from unittest.mock import patch

        settings = self._make_settings(nuxt_proxy_secret="")
        headers = {**AUTH_HEADERS, "x-proxy-secret": "anything"}

        with patch("app.deps.get_settings", return_value=settings):
            response = api_client.get("/api/v1/accounts", headers=headers)

        assert response.status_code == 500
        assert "NUXT_PROXY_SECRET not set" in response.json()["detail"]
