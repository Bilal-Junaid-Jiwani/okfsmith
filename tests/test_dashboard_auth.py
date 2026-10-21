"""Unit tests for the dashboard token auth contract (``okfsmith.dashboard.auth``).

The HTTP layer pins the headline behavior (``/health`` exempt, 401s, the
single-use query token) in ``tests/test_dashboard_api.py``; these tests pin
the contract at the ``TokenAuth`` level, including the edges the HTTP tests
do not exercise: scheme case-insensitivity, the query-token burn ordering,
and the 401 response shape.
"""

from __future__ import annotations

import re

from fastapi import Request

from okfsmith.dashboard.auth import TokenAuth, new_token


def _request(*, headers: dict | None = None, query: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/bundles",
        "query_string": query.encode(),
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }
    return Request(scope)


def test_new_token_is_urlsafe_unique() -> None:
    first, second = new_token(), new_token()
    assert isinstance(first, str) and first
    assert first != second
    # token_urlsafe(32) -> 43 chars; alphabet is URL-safe base64.
    assert len(first) == 43
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_bearer_header_accepted() -> None:
    auth = TokenAuth("secret-token")
    assert auth.check(_request(headers={"authorization": "Bearer secret-token"}))


def test_bearer_scheme_is_case_insensitive() -> None:
    auth = TokenAuth("secret-token")
    assert auth.check(_request(headers={"authorization": "bearer secret-token"}))
    assert auth.check(_request(headers={"authorization": "BEARER secret-token"}))


def test_bearer_value_is_stripped() -> None:
    auth = TokenAuth("secret-token")
    assert auth.check(_request(headers={"authorization": "Bearer   secret-token  "}))


def test_missing_or_wrong_credentials_rejected() -> None:
    auth = TokenAuth("secret-token")
    assert not auth.check(_request())
    assert not auth.check(_request(headers={"authorization": "Bearer wrong"}))
    assert not auth.check(_request(headers={"authorization": "Bearer"}))
    assert not auth.check(_request(headers={"authorization": "Token secret-token"}))
    # A wrong-length candidate must not raise through compare_digest.
    assert not auth.check(_request(headers={"authorization": "Bearer x"}))


def test_query_token_accepted_exactly_once() -> None:
    auth = TokenAuth("secret-token")
    assert auth.check(_request(query="token=secret-token"))
    assert not auth.check(_request(query="token=secret-token"))


def test_query_token_burn_does_not_break_bearer() -> None:
    auth = TokenAuth("secret-token")
    assert auth.check(_request(query="token=secret-token"))
    assert auth.check(_request(headers={"authorization": "Bearer secret-token"}))


def test_failed_query_token_does_not_burn_the_single_use() -> None:
    auth = TokenAuth("secret-token")
    assert not auth.check(_request(query="token=nope"))
    assert auth.check(_request(query="token=secret-token"))
    assert not auth.check(_request(query="token=secret-token"))


def test_error_response_shape() -> None:
    resp = TokenAuth("secret-token").error_response()
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    import json

    body = json.loads(resp.body.decode())
    assert body["error"] == "unauthorized"
    assert "token" in body["message"].lower()
