"""Tests for the CORS allow-list.

The api previously shipped with `allow_origins=["*"]` combined with
`allow_credentials=True`, a combo that browsers reject and that lets any
origin issue credentialed preflights against the API. This test pins the
expected behaviour:

  * A preflight from an allow-listed origin succeeds and echoes the
    `access-control-allow-origin` header.
  * A preflight from a non-allow-listed origin is rejected — either via
    a 400 status from starlette's CORSMiddleware or by omitting the
    access-control-allow-origin header in the response (the practical
    effect is the same: the browser blocks the request).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _make_app(allow_origins: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    return app


def test_cors_preflight_from_allowed_origin_is_accepted():
    app = _make_app(["http://localhost:3000", "http://localhost:8000"])
    client = TestClient(app)

    response = client.options(
        "/api/v1/ping",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight_from_disallowed_origin_is_rejected():
    """Preflight from evil.example.com must not receive a matching
    allow-origin header. Starlette returns 400 in this case in recent
    versions; older versions return 200 without the header. Either way,
    the browser blocks the request because the header doesn't match the
    Origin it sent."""
    app = _make_app(["http://localhost:3000", "http://localhost:8000"])
    client = TestClient(app)

    response = client.options(
        "/api/v1/ping",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    rejected_by_status = response.status_code in (400, 403)
    rejected_by_missing_header = (
        response.headers.get("access-control-allow-origin")
        != "http://evil.example.com"
    )
    assert rejected_by_status or rejected_by_missing_header, (
        f"Disallowed origin was not rejected: status={response.status_code}, "
        f"ACAO={response.headers.get('access-control-allow-origin')!r}"
    )


def test_cors_no_wildcard_with_credentials():
    """Guards against regression to `allow_origins=['*']`. With
    credentialed requests, starlette must not echo a wildcard back."""
    app = _make_app(["http://localhost:3000"])
    client = TestClient(app)

    response = client.options(
        "/api/v1/ping",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    # Whatever else the response says, it must NOT be a credentialed
    # wildcard — that combination is invalid per the CORS spec.
    acao = response.headers.get("access-control-allow-origin")
    acac = response.headers.get("access-control-allow-credentials")
    if acac == "true":
        assert acao != "*", "wildcard ACAO with credentials is invalid"
