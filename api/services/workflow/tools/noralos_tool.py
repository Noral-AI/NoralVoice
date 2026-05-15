"""Reverse-RPC tool executor for the ``noralos://`` URL scheme.

A NoralVoice workflow Agent node can reference a tool with a URL of the
form ``noralos://<plugin_id>/<tool_name>``. When the LLM invokes the
tool mid-call, the executor:

1. Resolves the organization's reverse-RPC callback URL + secret from
   the ``integration_webhooks`` table (populated by the NoralOS plugin
   during its lifecycle setup — see Phase 1A).
2. POSTs a JSON envelope to that callback URL with an HMAC-SHA256
   signature in the ``X-Noralos-Signature`` header.
3. Waits up to ``DEFAULT_TIMEOUT_SECONDS`` for the response.
4. Returns a tool-result dict to the LLM. Failures are surfaced as
   ``status="error"`` so the Agent node can recover (e.g. retry the
   call, fall back to a different tool, or end the call cleanly) but
   never crash the run.

Auth contract — HMAC-SHA256 over the serialized request body, hex-
encoded, sent in ``X-Noralos-Signature: sha256=<hex>``. Mirrors the
outbound webhook signing pattern in
``api/services/integration_webhooks.py`` but uses a separate secret
column on ``integration_webhooks`` (``reverse_rpc_secret``) so a leak
of one direction's secret doesn't compromise the other.

Failure surface — single attempt, 10s timeout. The Voice Agent's LLM
can retry by calling the tool again if it wants. We do NOT retry inside
the executor; reverse-RPC handlers on the NoralOS side may have
side-effects (creating tasks, sending messages) that mustn't double up.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from api.db import db_client

NORALOS_SCHEME = "noralos"
DEFAULT_TIMEOUT_SECONDS = 10.0
SIGNATURE_HEADER = "X-Noralos-Signature"
SCHEMA_VERSION_HEADER = "X-Noralos-Schema"
SCHEMA_VERSION = 1

# ``noralos://<plugin_id>/<tool_name>``. Plugin IDs follow the
# ``namespace.name`` convention (e.g. ``noralai.noralvoice``); tool
# names are lowercase snake_case.
_PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)+$")
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class NoralosToolError(Exception):
    """Raised for unrecoverable failures during reverse-RPC dispatch.

    The handler catches and turns these into ``status="error"`` results
    so the Agent node sees a graceful failure rather than a Python
    exception bubbling up.
    """


def is_noralos_url(url: str) -> bool:
    """Cheap scheme check used by the dispatcher to route URL-shaped
    tool configs to the right executor."""
    return url.lower().startswith(f"{NORALOS_SCHEME}://")


def parse_noralos_url(url: str) -> tuple[str, str]:
    """Split ``noralos://<plugin_id>/<tool_name>`` into the two parts.

    Raises ``NoralosToolError`` on any malformed input — we'd rather
    surface a clear "URL is wrong" message in the run log than ship a
    partial parse to a callback URL.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() != NORALOS_SCHEME:
        raise NoralosToolError(f"Expected `noralos://` URL, got `{parsed.scheme}://`")

    plugin_id = parsed.netloc
    tool_name = parsed.path.lstrip("/")

    if not plugin_id or not _PLUGIN_ID_PATTERN.match(plugin_id):
        raise NoralosToolError(
            f"Invalid plugin_id `{plugin_id}` (expected dotted lower-snake form)"
        )
    if not tool_name or "/" in tool_name or not _TOOL_NAME_PATTERN.match(tool_name):
        raise NoralosToolError(
            f"Invalid tool_name `{tool_name}` (expected lower-snake form)"
        )

    return plugin_id, tool_name


def sign_body(secret: str, body_bytes: bytes) -> str:
    """HMAC-SHA256 of the raw bytes, hex-encoded. Same convention as
    ``api.services.integration_webhooks.sign_payload``."""
    return hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()


def _error_result(error: str, code: str = "NORALOS_RPC_ERROR") -> Dict[str, Any]:
    """Build the tool-result envelope for an error. Shaped so the LLM
    sees ``{ok: false, error, code}`` regardless of where the failure
    happened (URL parse, DB lookup, HTTP failure, downstream rejection).
    """
    return {
        "status": "error",
        "ok": False,
        "error": error,
        "code": code,
    }


async def execute_noralos_tool(
    url: str,
    arguments: Dict[str, Any],
    organization_id: int,
    run_id: Optional[int] = None,
    workflow_uuid: Optional[str] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Dispatch a ``noralos://`` tool call.

    Returns a tool-result dict shaped to match the existing custom-tool
    flow:
        success: ``{"status": "success", "ok": True, "data": <result>}``
        failure: ``{"status": "error", "ok": False, "error": <msg>, "code": <short>}``

    Never raises — failures are surfaced via the result dict so the LLM
    can react (and the run keeps going). The dispatch is single-attempt
    by design; reverse-RPC handlers may have side-effects.
    """
    # 1. Parse the URL. Bad URLs are operator misconfigurations; surface
    #    them clearly so the run log shows where to look.
    try:
        plugin_id, tool_name = parse_noralos_url(url)
    except NoralosToolError as exc:
        logger.warning(f"noralos:// dispatch rejected: {exc}")
        return _error_result(str(exc), code="NORALOS_URL_INVALID")

    # 2. Look up the org's reverse-RPC callback URL + secret. If absent,
    #    the plugin hasn't been installed (or its install didn't include
    #    reverse-RPC config).
    config = await db_client.get_reverse_rpc_for_org(organization_id)
    if config is None or not config.reverse_rpc_url or not config.reverse_rpc_secret:
        logger.warning(
            f"noralos:// dispatch failed: org={organization_id} has no reverse-RPC config"
        )
        return _error_result(
            "No reverse-RPC integration registered for this organization",
            code="NORALOS_NOT_CONFIGURED",
        )

    # 3. Serialize the envelope deterministically (sort_keys so signing
    #    is stable across Python dict orderings).
    envelope = {
        "schemaVersion": SCHEMA_VERSION,
        "plugin_id": plugin_id,
        "tool_name": tool_name,
        "args": arguments,
        "run_id": run_id,
        "workflow_uuid": workflow_uuid,
        "organization_id": organization_id,
    }
    body_bytes = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    signature = sign_body(config.reverse_rpc_secret, body_bytes)

    # 4. POST. One attempt, 10s timeout. No retries — the receiver may
    #    have side-effects.
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: f"sha256={signature}",
        SCHEMA_VERSION_HEADER: str(SCHEMA_VERSION),
    }
    logger.info(
        f"noralos:// dispatch plugin={plugin_id} tool={tool_name} "
        f"org={organization_id} url={config.reverse_rpc_url[:60]}"
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                config.reverse_rpc_url, content=body_bytes, headers=headers
            )
    except httpx.TimeoutException:
        return _error_result(
            f"noralos://{plugin_id}/{tool_name} timed out after {timeout_seconds}s",
            code="NORALOS_TIMEOUT",
        )
    except httpx.HTTPError as exc:
        return _error_result(
            f"noralos://{plugin_id}/{tool_name} request failed: {type(exc).__name__}",
            code="NORALOS_CONNECTION_ERROR",
        )

    # 5. Translate the HTTP response. Receiver protocol is
    #    ``{ok: true, result}`` or ``{ok: false, error, code}``; we
    #    flatten that into the tool-result shape the LLM expects.
    if not (200 <= resp.status_code < 300):
        body_text = resp.text[:300]
        return _error_result(
            f"noralos://{plugin_id}/{tool_name} returned {resp.status_code}: {body_text}",
            code=f"NORALOS_HTTP_{resp.status_code}",
        )

    try:
        payload = resp.json()
    except Exception:
        return _error_result(
            f"noralos://{plugin_id}/{tool_name} returned non-JSON response",
            code="NORALOS_BAD_RESPONSE",
        )

    if isinstance(payload, dict) and payload.get("ok") is False:
        return _error_result(
            payload.get("error", "Reverse-RPC handler returned ok=false"),
            code=payload.get("code", "NORALOS_HANDLER_REJECTED"),
        )

    result_data = (
        payload.get("result")
        if isinstance(payload, dict) and "result" in payload
        else payload
    )
    return {
        "status": "success",
        "ok": True,
        "data": result_data,
    }
