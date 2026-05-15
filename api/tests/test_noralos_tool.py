"""Unit tests for the ``noralos://`` reverse-RPC tool executor."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from api.services.workflow.tools.noralos_tool import (
    SCHEMA_VERSION,
    SIGNATURE_HEADER,
    NoralosToolError,
    execute_noralos_tool,
    is_noralos_url,
    parse_noralos_url,
    sign_body,
)


# ---- URL parsing -------------------------------------------------------

def test_is_noralos_url_matches_scheme():
    assert is_noralos_url("noralos://noralai.noralvoice/get_agent_status")
    assert is_noralos_url("NoRaLoS://x.y/z")  # case-insensitive
    assert not is_noralos_url("https://example.com")
    assert not is_noralos_url("http://noralos.example.com")
    assert not is_noralos_url("")


def test_parse_noralos_url_happy_path():
    plugin_id, tool_name = parse_noralos_url(
        "noralos://noralai.noralvoice/get_agent_status"
    )
    assert plugin_id == "noralai.noralvoice"
    assert tool_name == "get_agent_status"


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://noralai.noralvoice/foo",
        "noralos://no-dot/tool_name",
        "noralos://noralai.noralvoice/Has-Dashes",
        "noralos://noralai.noralvoice/",
        "noralos:///get_agent_status",
        "noralos://noralai.noralvoice/sub/path",
    ],
)
def test_parse_noralos_url_rejects(bad_url):
    with pytest.raises(NoralosToolError):
        parse_noralos_url(bad_url)


# ---- HMAC --------------------------------------------------------------

def test_sign_body_matches_reference_hmac():
    secret = "test-secret"
    body = b'{"x":1}'
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    assert sign_body(secret, body) == expected


# ---- end-to-end dispatch with a mocked httpx ----------------------------

class _FakeWebhook:
    def __init__(self, url: str, secret: str):
        self.reverse_rpc_url = url
        self.reverse_rpc_secret = secret


@pytest.fixture
def mock_reverse_config(monkeypatch):
    """Patch the db_client used by the executor."""
    fake = _FakeWebhook(
        url="https://noralos.example.com/api/plugins/noralai.noralvoice/api/reverse-tool",
        secret="hmac-secret",
    )

    async def fake_get(org_id):
        return fake

    from api.services.workflow.tools import noralos_tool as mod

    monkeypatch.setattr(
        mod.db_client, "get_reverse_rpc_for_org", fake_get, raising=False
    )
    return fake


@pytest.mark.asyncio
async def test_execute_noralos_tool_signs_and_posts(monkeypatch, mock_reverse_config):
    captured: dict = {}

    class _StubResponse:
        def __init__(self):
            self.status_code = 200
            self.text = ""

        def json(self):
            return {"ok": True, "result": {"status": "active"}}

    class _StubClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, content, headers):
            captured["url"] = url
            captured["body"] = content
            captured["headers"] = headers
            return _StubResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)

    result = await execute_noralos_tool(
        url="noralos://noralai.noralvoice/get_agent_status",
        arguments={"agent_id": "abc"},
        organization_id=42,
        run_id=99,
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["data"] == {"status": "active"}

    sent_body = json.loads(captured["body"].decode("utf-8"))
    assert sent_body["plugin_id"] == "noralai.noralvoice"
    assert sent_body["tool_name"] == "get_agent_status"
    assert sent_body["args"] == {"agent_id": "abc"}
    assert sent_body["organization_id"] == 42
    assert sent_body["run_id"] == 99
    assert sent_body["schemaVersion"] == SCHEMA_VERSION

    expected_sig = hmac.new(
        mock_reverse_config.reverse_rpc_secret.encode("utf-8"),
        captured["body"],
        hashlib.sha256,
    ).hexdigest()
    assert captured["headers"][SIGNATURE_HEADER] == f"sha256={expected_sig}"


@pytest.mark.asyncio
async def test_execute_noralos_tool_returns_not_configured_when_org_has_no_reverse_rpc(
    monkeypatch,
):
    async def fake_get(org_id):
        return None

    from api.services.workflow.tools import noralos_tool as mod

    monkeypatch.setattr(
        mod.db_client, "get_reverse_rpc_for_org", fake_get, raising=False
    )

    result = await execute_noralos_tool(
        url="noralos://noralai.noralvoice/get_agent_status",
        arguments={"agent_id": "abc"},
        organization_id=42,
    )

    assert result["ok"] is False
    assert result["code"] == "NORALOS_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_execute_noralos_tool_propagates_downstream_error(
    monkeypatch, mock_reverse_config
):
    class _StubResponse:
        def __init__(self):
            self.status_code = 200
            self.text = ""

        def json(self):
            return {"ok": False, "error": "NOT_FOUND", "code": "NOT_FOUND"}

    class _StubClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, content, headers):
            return _StubResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)

    result = await execute_noralos_tool(
        url="noralos://noralai.noralvoice/lookup_customer",
        arguments={"identifier": "missing@example.com"},
        organization_id=42,
    )

    assert result["ok"] is False
    assert result["code"] == "NOT_FOUND"
    assert "NOT_FOUND" in result["error"]
