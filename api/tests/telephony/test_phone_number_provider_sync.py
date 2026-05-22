"""Locks in the create-phone-number provider-sync contract.

The route at ``api.routes.organization.create_phone_number`` calls
``_sync_inbound_for_phone_number`` only when ``inbound_workflow_id`` is provided
on create (see route source). That asymmetry is what causes Twilio to keep its
default ``voice_url`` on newly-registered numbers — inbound callers hear the
provider's stock "this number has not been configured" greeting. The UI
(PhoneNumberDialog) warns the user before they hit Save. This test pins the
backend contract so neither side drifts unnoticed: if the backend later starts
syncing unconditionally, the UI warning becomes redundant and we want to know.
"""

from unittest.mock import AsyncMock, patch

import pytest

from api.db.models import OrganizationModel, UserModel
from api.schemas.telephony_phone_number import ProviderSyncStatus


@pytest.fixture
async def org_user_and_config(db_session, async_session):
    """Org + user + a Twilio telephony config wired to ``user.selected_organization_id``."""
    org = OrganizationModel(provider_id="test-org-phone-sync")
    async_session.add(org)
    await async_session.flush()

    user = UserModel(
        provider_id="test-user-phone-sync", selected_organization_id=org.id
    )
    async_session.add(user)
    await async_session.flush()

    config = await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="Twilio Test",
        provider="twilio",
        credentials={
            "account_sid": "ACtest_phone_sync_0000000000000000",
            "auth_token": "twilio_test_auth_token_value",
        },
    )
    return org, user, config


async def test_create_phone_number_without_workflow_skips_provider_sync(
    test_client_factory, org_user_and_config
):
    """No ``inbound_workflow_id`` on create → no Twilio VoiceUrl PATCH attempt.

    This is the path that bit prod: a number registered without a workflow
    keeps the provider's default VoiceUrl, callers hear the provider's "not
    configured" greeting, and nothing surfaces server-side. The UI's
    ``AlertDialog`` in ``PhoneNumberDialog.tsx`` is the user-facing guard
    against this — if you change this assertion, update the UI warning too.
    """
    _, user, config = org_user_and_config

    with patch(
        "api.routes.organization._sync_inbound_for_phone_number",
        new_callable=AsyncMock,
        return_value=ProviderSyncStatus(ok=True),
    ) as mock_sync:
        async with test_client_factory(user) as client:
            res = await client.post(
                f"/api/v1/organizations/telephony-configs/{config.id}/phone-numbers",
                json={
                    "address": "+15551230001",
                    "country_code": "US",
                    "is_active": True,
                    "is_default_caller_id": False,
                },
            )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["inbound_workflow_id"] is None
    assert body.get("provider_sync") is None
    assert mock_sync.await_count == 0, (
        "Backend should NOT push to provider on create-without-workflow — "
        "if this changed deliberately, drop the UI no-workflow AlertDialog."
    )


async def test_create_phone_number_with_workflow_calls_provider_sync(
    test_client_factory, org_user_and_config, db_session
):
    """``inbound_workflow_id`` provided → exactly one provider sync attempt."""
    _, user, config = org_user_and_config

    workflow = await db_session.create_workflow(
        name="Inbound test workflow",
        workflow_definition={
            "nodes": [
                {
                    "id": "1",
                    "type": "startCall",
                    "data": {"name": "Start", "prompt": "Hi"},
                },
                {
                    "id": "2",
                    "type": "endCall",
                    "data": {"name": "End", "prompt": "Bye"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "1", "target": "2", "data": {"label": "End"}}
            ],
        },
        user_id=user.id,
        organization_id=user.selected_organization_id,
    )

    with patch(
        "api.routes.organization._sync_inbound_for_phone_number",
        new_callable=AsyncMock,
        return_value=ProviderSyncStatus(ok=True),
    ) as mock_sync:
        async with test_client_factory(user) as client:
            res = await client.post(
                f"/api/v1/organizations/telephony-configs/{config.id}/phone-numbers",
                json={
                    "address": "+15551230002",
                    "country_code": "US",
                    "inbound_workflow_id": workflow.id,
                    "is_active": True,
                    "is_default_caller_id": False,
                },
            )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["inbound_workflow_id"] == workflow.id
    assert body["provider_sync"] == {"ok": True, "message": None}
    assert mock_sync.await_count == 1
    args = mock_sync.await_args.args
    assert args[0] == config.id
    assert args[1] == user.selected_organization_id
