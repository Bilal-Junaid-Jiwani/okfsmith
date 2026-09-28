"""Per-launch token authentication for the dashboard.

One random token is minted at server launch (see ``server.py``). API routes
under ``/api/v1`` (except ``/health``) require it as an
``Authorization: Bearer <token>`` header, compared with
:func:`hmac.compare_digest`.

The token is also accepted **once** via the ``?token=`` query parameter so
the freshly opened browser tab can bootstrap; the frontend must then scrub
it from the URL and switch to the header. After that single use the query
form is burned. The token value is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse


def new_token() -> str:
    """Mint a fresh per-launch token."""
    return secrets.token_urlsafe(32)


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


@dataclass
class TokenAuth:
    """Holds the launch token and the single-use query-token state."""

    token: str
    _query_token_used: bool = field(default=False, init=False, repr=False)

    def _matches(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        # compare_digest needs same types; hash both sides first so a
        # length difference cannot leak via timing either.
        expected = hashlib.sha256(self.token.encode()).digest()
        got = hashlib.sha256(candidate.encode()).digest()
        return hmac.compare_digest(expected, got)

    def check(self, request: Request) -> bool:
        """True when *request* carries valid credentials."""
        if self._matches(_bearer_token(request)):
            return True
        query_token = request.query_params.get("token")
        if query_token and not self._query_token_used and self._matches(query_token):
            self._query_token_used = True
            return True
        return False

    def error_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": "unauthorized",
                "message": "Missing or invalid dashboard token.",
                "hint": "Open the dashboard via the URL printed by "
                "'okfsmith dashboard' (it carries a one-time ?token=); the "
                "app then sends Authorization: Bearer <token> headers.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
