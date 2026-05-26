"""Tests for delegated-identity API key authentication.

When NoralOS plugin workers call into NoralVoice on behalf of a human
user (e.g. Brooklyn creating a workflow because Quentin asked), they
present a service ``X-API-Key`` plus ``X-Noralos-Actor-User-*`` headers
identifying the triggering user.

This module pins the behavior of ``_handle_api_key_auth``:

- A delegation-capable key + actor headers → JIT-provision the user via
  ``provider_id="noralos:<actor>"`` (same path browser SSO uses).
- A delegation-capable key + no actor headers → fall back to
  ``api_key.created_by`` ownership (no orphaned rows).
- A non-delegation key + actor headers → headers ignored; ownership
  stays with ``api_key.created_by`` (no privilege escalation).
- Email is synced only on first JIT creation; existing users are not
  overwritten.

The same JIT call ``get_or_create_user_by_provider_id`` is used by the
browser SSO flow in ``api/services/auth/noral_sso.py``, so a user
arriving via either path lands on the same ``users`` row.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.services.auth.depends import _handle_api_key_auth


def _make_api_key(*, delegation_capable: bool, created_by: int | None = 42):
    key = MagicMock()
    key.id = 1
    key.organization_id = 100
    key.delegation_capable = delegation_capable
    key.created_by = created_by
    key.key_prefix = "nv_abcd"
    return key


def _make_user(user_id: int, email: str | None = None):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.selected_organization_id = None
    return user


@pytest.mark.asyncio
async def test_delegation_capable_with_actor_creates_jit_user():
    """Delegation-capable key + actor headers → JIT-provisioned user."""
    api_key_model = _make_api_key(delegation_capable=True)
    jit_user = _make_user(user_id=7, email=None)

    with patch(
        "api.services.auth.depends.db_client.validate_api_key",
        new=AsyncMock(return_value=api_key_model),
    ), patch(
        "api.services.auth.depends.db_client.get_or_create_user_by_provider_id",
        new=AsyncMock(return_value=(jit_user, True)),
    ), patch(
        "api.services.auth.depends.db_client.update_user_email",
        new=AsyncMock(),
    ) as mock_update_email:
        user = await _handle_api_key_auth(
            "nv_test_key",
            actor_user_id="ba-user-quentin",
            actor_user_email="quentin@noral.ai",
        )

    assert user.id == 7
    assert user.email == "quentin@noral.ai"
    assert user.selected_organization_id == 100
    mock_update_email.assert_awaited_once_with(7, "quentin@noral.ai")


@pytest.mark.asyncio
async def test_delegation_capable_reuses_existing_user_without_email_overwrite():
    """JIT returning was_created=False does NOT touch email."""
    api_key_model = _make_api_key(delegation_capable=True)
    existing_user = _make_user(user_id=7, email="existing@old.example")

    with patch(
        "api.services.auth.depends.db_client.validate_api_key",
        new=AsyncMock(return_value=api_key_model),
    ), patch(
        "api.services.auth.depends.db_client.get_or_create_user_by_provider_id",
        new=AsyncMock(return_value=(existing_user, False)),
    ), patch(
        "api.services.auth.depends.db_client.update_user_email",
        new=AsyncMock(),
    ) as mock_update_email:
        user = await _handle_api_key_auth(
            "nv_test_key",
            actor_user_id="ba-user-quentin",
            actor_user_email="newer@example.com",
        )

    assert user.id == 7
    assert user.email == "existing@old.example"
    mock_update_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_delegation_capable_without_actor_falls_back_to_created_by():
    """No actor header → behaves like a plain key (no JIT, no orphan)."""
    api_key_model = _make_api_key(delegation_capable=True, created_by=42)
    creator = _make_user(user_id=42, email="service@noral.ai")

    with patch(
        "api.services.auth.depends.db_client.validate_api_key",
        new=AsyncMock(return_value=api_key_model),
    ), patch(
        "api.services.auth.depends.db_client.get_user_by_id",
        new=AsyncMock(return_value=creator),
    ), patch(
        "api.services.auth.depends.db_client.get_or_create_user_by_provider_id",
        new=AsyncMock(),
    ) as mock_jit:
        user = await _handle_api_key_auth("nv_test_key")

    assert user.id == 42
    assert user.selected_organization_id == 100
    mock_jit.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_delegation_key_ignores_actor_headers():
    """Pinned safety property: non-delegation keys must NOT honor actor headers."""
    api_key_model = _make_api_key(delegation_capable=False, created_by=42)
    creator = _make_user(user_id=42, email="user@example.com")

    with patch(
        "api.services.auth.depends.db_client.validate_api_key",
        new=AsyncMock(return_value=api_key_model),
    ), patch(
        "api.services.auth.depends.db_client.get_user_by_id",
        new=AsyncMock(return_value=creator),
    ), patch(
        "api.services.auth.depends.db_client.get_or_create_user_by_provider_id",
        new=AsyncMock(),
    ) as mock_jit:
        user = await _handle_api_key_auth(
            "nv_test_key",
            actor_user_id="ba-user-quentin",
            actor_user_email="quentin@noral.ai",
        )

    # Ownership stays with api_key.created_by, NOT the actor.
    assert user.id == 42
    mock_jit.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_api_key_still_rejected():
    """Regression: bad key still 401s regardless of actor headers."""
    with patch(
        "api.services.auth.depends.db_client.validate_api_key",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await _handle_api_key_auth(
                "nv_bad_key",
                actor_user_id="ba-user-quentin",
            )
    assert excinfo.value.status_code == 401
