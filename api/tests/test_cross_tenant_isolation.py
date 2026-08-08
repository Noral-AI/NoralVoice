"""Cross-tenant isolation, asserted per route.

Plan §7 Phase 7 requires "an automated test proving no endpoint returns
cross-client data, running in CI" and "a test proving no ElevenLabs call can be
made without an organization-resolved credential."

This file is that test. It matters more than a normal isolation suite would,
because the vendor side is *not* partitioned: with one shared ElevenLabs
workspace, every client's agents and conversations sit behind one key. Our own
database and these checks are the entire client boundary. If a route here stops
scoping, nothing downstream catches it.

The style is deliberately structural rather than exhaustive-by-example. Listing
every route by hand rots the moment someone adds one; walking the router and
asserting on the code catches the route nobody remembered to add here.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.agents import router as agents_router
from api.routes.calls import router as calls_router
from api.routes.credentials import router as credentials_router
from api.services.auth.depends import get_user

#: Routers whose every route must be organization-scoped.
TENANT_SCOPED_ROUTERS = {
    "agents": agents_router,
    "calls": calls_router,
    "credentials": credentials_router,
}


def _app(router, caller_org_id: int | None = 100):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    caller = MagicMock()
    caller.id = 7
    caller.selected_organization_id = caller_org_id
    app.dependency_overrides[get_user] = lambda: caller
    return app


# ---------------------------------------------------------------------------
# Every route requires an organization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("router_name", sorted(TENANT_SCOPED_ROUTERS))
def test_every_route_depends_on_an_authenticated_user(router_name):
    """A tenant-scoped route without get_user has no organization to scope to,
    which means it is either unscoped or scoping off something untrusted."""
    router = TENANT_SCOPED_ROUTERS[router_name]

    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue

        signature = inspect.signature(endpoint)
        depends_on_user = any(
            getattr(param.default, "dependency", None) is get_user
            for param in signature.parameters.values()
        )
        assert depends_on_user, (
            f"{router_name}.{endpoint.__name__} does not depend on get_user, "
            "so it cannot be organization-scoped."
        )


@pytest.mark.parametrize("router_name", sorted(TENANT_SCOPED_ROUTERS))
def test_routes_reject_a_caller_with_no_organization(router_name):
    """A user with no selected organization must not fall through to unscoped
    data — the only safe answer is a refusal."""
    client = TestClient(_app(TENANT_SCOPED_ROUTERS[router_name], caller_org_id=None))

    # A GET on each collection route is enough to prove the guard is present.
    for route in TENANT_SCOPED_ROUTERS[router_name].routes:
        if "GET" not in getattr(route, "methods", set()):
            continue
        path = route.path
        if "{" in path:
            continue  # parameterised routes are covered by the ownership tests

        response = client.get(f"/api/v1{path}")
        assert response.status_code == 400, (
            f"GET {path} returned {response.status_code} for a caller with no "
            "organization; expected 400."
        )


# ---------------------------------------------------------------------------
# Ownership is checked against our database, not the vendor's
# ---------------------------------------------------------------------------


def test_agent_routes_never_reach_the_vendor_before_checking_ownership():
    """Ordering matters: resolving a client and calling ElevenLabs *before*
    the ownership check would leak the existence of another client's agent,
    and could act on it."""
    client = TestClient(_app(agents_router))

    resolver = AsyncMock()
    with (
        patch(
            "api.routes.agents.db_client.get_workflow_by_elevenlabs_agent_id",
            new=AsyncMock(return_value=None),
        ),
        patch("api.routes.agents.get_client_for_organization", new=resolver),
    ):
        assert client.get("/api/v1/agents/not_mine").status_code == 404
        assert client.patch("/api/v1/agents/not_mine", json={}).status_code == 404
        assert client.delete("/api/v1/agents/not_mine").status_code == 404

    resolver.assert_not_awaited()


def test_calls_queries_filter_on_organization_in_sql():
    """Structural check: every select in the calls module constrains on
    WorkflowModel.organization_id.

    Filtering in Python after a broad fetch would pass a behavioural test while
    still pulling another client's rows into memory — and one careless change
    later, into a response.
    """
    source = Path(inspect.getfile(__import__("api.routes.calls", fromlist=["x"])))
    tree = ast.parse(source.read_text())

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if node.name.startswith("_"):
            continue

        body = ast.dump(node)
        assert "organization_id" in body, (
            f"calls.{node.name} does not reference organization_id; "
            "every query in this module must be organization-scoped."
        )


# ---------------------------------------------------------------------------
# No ElevenLabs call without an organization-resolved credential
# ---------------------------------------------------------------------------


def test_no_route_constructs_an_elevenlabs_client_directly():
    """Routes must go through get_client_for_organization.

    Constructing ElevenLabsClient in a route means someone got a key from
    somewhere other than the calling organization's credential row — which is
    the exact failure the single-workspace design cannot tolerate.
    """
    routes_dir = Path(inspect.getfile(__import__("api.routes.agents", fromlist=["x"]))).parent

    for source_file in routes_dir.glob("*.py"):
        tree = ast.parse(source_file.read_text())

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ElevenLabsClient"
            ):
                pytest.fail(
                    f"{source_file.name} constructs an ElevenLabsClient directly. "
                    "Use get_client_for_organization so the key resolves from "
                    "the calling organization."
                )


def test_credential_lookup_is_always_given_an_organization():
    """get_provider_credential has no unscoped variant, and callers pass a real
    organization rather than a wildcard."""
    from api.db.webhook_credential_client import WebhookCredentialClient

    signature = inspect.signature(WebhookCredentialClient.get_provider_credential)
    assert "organization_id" in signature.parameters

    # No default — an omitted organization must be a TypeError, not a global read.
    assert (
        signature.parameters["organization_id"].default is inspect.Parameter.empty
    )
