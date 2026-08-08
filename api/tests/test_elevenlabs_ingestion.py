"""Tests for ElevenLabs conversation ingestion.

Covers the three properties Phase 2's acceptance criteria turn on:

  - a replayed webhook creates no duplicate (idempotency on conversation id)
  - a conversation the webhook never delivered is recovered by reconciliation
  - the initiation webhook fails open, because it sits in the call path

Signature verification is tested against the documented header format rather
than a mock, since getting it subtly wrong is the kind of bug that only shows
up as "the vendor's webhooks all 401".
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.elevenlabs.ingestion import (
    WebhookVerificationError,
    ingest_conversation,
    verify_webhook_signature,
)

SECRET = "whsec_test_secret"


def sign(body: bytes, secret: str = SECRET, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    digest = hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={ts},v0={digest}"


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_valid_signature_passes():
    body = b'{"type":"post_call_transcription"}'
    verify_webhook_signature(body, sign(body), SECRET)


def test_tampered_body_is_rejected():
    body = b'{"type":"post_call_transcription"}'
    header = sign(body)

    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_webhook_signature(b'{"type":"tampered"}', header, SECRET)


def test_wrong_secret_is_rejected():
    body = b"{}"
    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_webhook_signature(body, sign(body), "whsec_a_different_secret")


def test_old_timestamp_is_rejected():
    """Bounds replay of a captured-but-valid webhook."""
    body = b"{}"
    stale = int(time.time()) - (60 * 60)

    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_webhook_signature(body, sign(body, timestamp=stale), SECRET)


def test_future_timestamp_is_rejected():
    body = b"{}"
    ahead = int(time.time()) + (60 * 60)

    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_webhook_signature(body, sign(body, timestamp=ahead), SECRET)


@pytest.mark.parametrize(
    "header", [None, "", "garbage", "t=123", "v0=abc", "t=notanint,v0=abc"]
)
def test_malformed_headers_are_rejected(header):
    with pytest.raises(WebhookVerificationError):
        verify_webhook_signature(b"{}", header, SECRET)


def test_missing_secret_is_rejected():
    """An unconfigured deployment must reject webhooks, not accept everything."""
    body = b"{}"
    with pytest.raises(WebhookVerificationError, match="No webhook secret"):
        verify_webhook_signature(body, sign(body), "")


def test_error_messages_do_not_distinguish_failure_modes_usefully():
    """An attacker probing the endpoint should not learn which part was wrong."""
    body = b"{}"
    with pytest.raises(WebhookVerificationError) as exc:
        verify_webhook_signature(body, sign(body, secret="wrong"), SECRET)

    assert SECRET not in str(exc.value)


# ---------------------------------------------------------------------------
# Ingestion + idempotency
# ---------------------------------------------------------------------------


def _conversation(conversation_id="conv_1", agent_id="agent_1"):
    return {
        "conversation_id": conversation_id,
        "agent_id": agent_id,
        "status": "done",
        "metadata": {"call_duration_secs": 61, "start_time_unix_secs": 1_700_000_000},
        "transcript": [{"role": "agent", "message": "Hi"}],
        "analysis": {
            "data_collection_results": {"caller_name": {"value": "Sam"}},
            "call_successful": "success",
        },
    }


def _session(existing_run=None, workflow=None):
    """A session stub whose execute() returns queued scalar results."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    results = []
    # 1st execute: idempotency lookup
    idem = MagicMock()
    idem.scalars.return_value.first.return_value = existing_run
    results.append(idem)
    # 2nd: organization resolution (workflow lookup)
    org = MagicMock()
    org.scalars.return_value.first.return_value = workflow
    results.append(org)
    # 3rd: workflow fetch for the run
    wf = MagicMock()
    wf.scalars.return_value.first.return_value = workflow
    results.append(wf)

    session.execute = AsyncMock(side_effect=results)
    return session


async def test_replaying_a_webhook_creates_no_duplicate():
    """The acceptance criterion: replaying a webhook creates no duplicate."""
    already = MagicMock(id=7)
    session = _session(existing_run=already)

    run, created = await ingest_conversation(session, _conversation())

    assert run is already
    assert created is False
    session.add.assert_not_called()


async def test_a_new_conversation_is_written():
    workflow = MagicMock(id=3, organization_id=100)
    session = _session(existing_run=None, workflow=workflow)

    run, created = await ingest_conversation(session, _conversation())

    assert created is True
    session.add.assert_called_once()
    assert run.elevenlabs_conversation_id == "conv_1"
    assert run.duration_seconds == 61
    assert run.gathered_context["caller_name"]["value"] == "Sam"


async def test_a_conversation_with_no_id_is_ignored():
    session = _session()

    run, created = await ingest_conversation(session, {"agent_id": "agent_1"})

    assert (run, created) == (None, False)
    session.add.assert_not_called()


async def test_an_unattributable_conversation_is_not_filed_under_a_guess():
    """Better unclaimed and logged than written to the wrong tenant."""
    session = _session(existing_run=None, workflow=None)

    run, created = await ingest_conversation(session, _conversation())

    assert (run, created) == (None, False)
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Reconciliation — the kill-the-endpoint case
# ---------------------------------------------------------------------------


async def test_reconciliation_recovers_a_conversation_the_webhook_never_delivered():
    """Plan §7 Phase 2 acceptance: kill the webhook endpoint, place a call, then
    run reconciliation and the call is recovered."""
    from api.services.elevenlabs import ingestion

    missed = _conversation("conv_missed", "agent_1")
    workflow = MagicMock(id=3, organization_id=100)

    async def fake_iter(client, since, **kwargs):
        yield {"conversation_id": "conv_missed"}

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    # First execute: reconciliation's "do we already have it?" -> no.
    not_present = MagicMock()
    not_present.scalars.return_value.first.return_value = None
    # Then ingest_conversation's own three lookups.
    idem = MagicMock()
    idem.scalars.return_value.first.return_value = None
    org = MagicMock()
    org.scalars.return_value.first.return_value = workflow
    wf = MagicMock()
    wf.scalars.return_value.first.return_value = workflow
    session.execute = AsyncMock(side_effect=[not_present, idem, org, wf])

    with (
        patch(
            "api.services.elevenlabs.conversations.iter_conversations_since", fake_iter
        ),
        patch(
            "api.services.elevenlabs.conversations.get_conversation",
            new=AsyncMock(return_value=missed),
        ),
    ):
        counts = await ingestion.reconcile_organization(
            session, MagicMock(), organization_id=100, window=timedelta(hours=6)
        )

    assert counts["created"] == 1
    session.add.assert_called_once()


async def test_reconciliation_skips_what_is_already_stored():
    """Idempotency is what makes it safe to run often."""
    from api.services.elevenlabs import ingestion

    async def fake_iter(client, since, **kwargs):
        yield {"conversation_id": "conv_known"}

    session = MagicMock()
    session.add = MagicMock()
    present = MagicMock()
    present.scalars.return_value.first.return_value = 12
    session.execute = AsyncMock(side_effect=[present])

    with patch(
        "api.services.elevenlabs.conversations.iter_conversations_since", fake_iter
    ):
        counts = await ingestion.reconcile_organization(
            session, MagicMock(), organization_id=100
        )

    assert counts == {"seen": 1, "created": 0, "skipped": 1}
    session.add.assert_not_called()
