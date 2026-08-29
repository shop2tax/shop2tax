"""Unit tests for the Sentry before_send scrubber (app.main._scrub_sentry_event).

Guards the F6 fix: the Nuxt proxy secret and x-user-* PII must never leave the
instance in a captured Sentry event's request headers.
"""

from typing import Any, cast

from app.main import _scrub_sentry_event

FILTERED = "[Filtered]"


def _scrub(event: dict[str, Any]) -> dict[str, Any]:
    """Call the scrubber with plain test dicts (Sentry's Event/Hint are TypedDicts)."""
    return cast("dict[str, Any]", _scrub_sentry_event(cast("Any", event), cast("Any", {})))


class TestSentryScrub:
    """Redaction and resilience of the Sentry request-header scrubber."""

    def should_redact_proxy_secret_and_user_headers(self) -> None:
        event = {
            "request": {
                "headers": {
                    "x-proxy-secret": "super-secret-value",
                    "x-user-id": "00000000-0000-0000-0000-000000000000",
                    "x-user-email": "owner@example.com",
                    "x-user-name": "Owner",
                    "content-type": "application/json",
                },
            },
        }

        headers = _scrub(event)["request"]["headers"]

        assert headers["x-proxy-secret"] == FILTERED
        assert headers["x-user-id"] == FILTERED
        assert headers["x-user-email"] == FILTERED
        assert headers["x-user-name"] == FILTERED
        # Non-sensitive header is untouched
        assert headers["content-type"] == "application/json"
        # The raw secret must not appear anywhere in the event
        assert "super-secret-value" not in repr(_scrub(event))

    def should_match_header_names_case_insensitively(self) -> None:
        event = {"request": {"headers": {"X-Proxy-Secret": "s", "X-User-Email": "a@b.de"}}}

        headers = _scrub(event)["request"]["headers"]

        assert headers["X-Proxy-Secret"] == FILTERED
        assert headers["X-User-Email"] == FILTERED

    def should_return_event_unchanged_when_request_absent(self) -> None:
        assert _scrub({"exception": {"values": []}}) == {"exception": {"values": []}}

    def should_return_event_unchanged_when_headers_absent(self) -> None:
        assert _scrub({"request": {"url": "http://api/x"}}) == {"request": {"url": "http://api/x"}}

    def should_return_event_unchanged_when_headers_not_a_dict(self) -> None:
        assert _scrub({"request": {"headers": "not-a-dict"}}) == {"request": {"headers": "not-a-dict"}}

    def should_not_raise_on_empty_event(self) -> None:
        assert _scrub({}) == {}
