"""HTTP client for the ElevenLabs Agents API.

**The central rule of this module: there is no ambient credential.**

Every ElevenLabs call resolves its API key from the calling organization or
fails. There is no module-level client, no default workspace, and no fallback
to the environment. On a single shared workspace (plan §5) this resolution path
is the control actually doing the isolation work, so it is written to make the
unsafe thing impossible rather than merely discouraged:

- ``ElevenLabsClient`` cannot be constructed without an ``organization_id``.
- The only way to obtain one is :func:`get_client_for_organization`, which
  reads that organization's credential row and raises if it is absent.
- No cached instance is shared between organizations.

If you find yourself wanting a module-level client "just for a script", the
answer is to resolve one for the organization the script is acting on.
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx
from loguru import logger

API_BASE_URL = "https://api.elevenlabs.io"
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Header ElevenLabs expects the API key in.
API_KEY_HEADER = "xi-api-key"

#: Provider name for this integration's credential rows.
PROVIDER = "elevenlabs"


class ElevenLabsError(RuntimeError):
    """Base class for ElevenLabs integration failures."""


class MissingCredentialError(ElevenLabsError):
    """Raised when an organization has no usable ElevenLabs credential.

    Distinct from an API error so callers can tell "this client has not been
    set up yet" (fix: enter a key in Settings) from "the call failed".
    """


class ElevenLabsAPIError(ElevenLabsError):
    """Raised when ElevenLabs returns a non-success status.

    The response body is included because it carries the vendor's error detail,
    but the request headers are never included — they hold the API key.
    """

    def __init__(self, status_code: int, detail: str, *, method: str, path: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"ElevenLabs {method} {path} failed with {status_code}: {detail}")


class ElevenLabsClient:
    """A per-organization ElevenLabs API client.

    Construct via :func:`get_client_for_organization`, not directly — the
    constructor takes a raw key and cannot verify it belongs to the
    organization it is labelled with.
    """

    def __init__(
        self,
        api_key: str,
        organization_id: int,
        *,
        base_url: str = API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if not api_key:
            raise MissingCredentialError(
                "Refusing to build an ElevenLabs client with an empty API key"
            )
        if organization_id is None:
            raise ValueError(
                "ElevenLabsClient requires an organization_id — there is no "
                "unscoped ElevenLabs access"
            )

        self._api_key = api_key
        self.organization_id = organization_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def __repr__(self) -> str:
        # Never render the key, not even truncated. Reprs end up in logs.
        return f"<ElevenLabsClient organization_id={self.organization_id}>"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            API_KEY_HEADER: self._api_key,
            "Content-Type": "application/json",
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        """Issue a request and return the decoded body.

        Raises:
            ElevenLabsAPIError: on any non-2xx response.
        """
        url = f"{self._base_url}{path}"

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.request(
                method,
                url,
                headers=self._headers,
                params=params,
                json=json,
            )

        if response.status_code >= 400:
            # Logs the org, method and path — never the headers, which carry
            # the key, and never the request body, which may carry one.
            logger.warning(
                f"ElevenLabs {method} {path} -> {response.status_code} "
                f"(organization {self.organization_id})"
            )
            raise ElevenLabsAPIError(
                response.status_code,
                response.text[:500],
                method=method,
                path=path,
            )

        if response.status_code == 204 or not response.content:
            return None

        return response.json()

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, **kwargs)

    async def get_bytes(self, path: str) -> bytes:
        """Fetch a binary body — conversation audio, for instance."""
        url = f"{self._base_url}{path}"

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.get(url, headers=self._headers)

        if response.status_code >= 400:
            logger.warning(
                f"ElevenLabs GET {path} -> {response.status_code} "
                f"(organization {self.organization_id})"
            )
            raise ElevenLabsAPIError(
                response.status_code,
                response.text[:500],
                method="GET",
                path=path,
            )

        return response.content


async def get_client_for_organization(organization_id: int) -> ElevenLabsClient:
    """Resolve the ElevenLabs client for an organization.

    This is the only supported way to reach ElevenLabs. It exists so that the
    credential lookup cannot be skipped: there is no cached client to reuse and
    no environment variable to fall back to.

    Raises:
        MissingCredentialError: if the organization has no active credential,
            or the stored value cannot be decrypted.
    """
    # Imported here rather than at module scope to keep this module importable
    # from the DB layer without a cycle.
    from api.db import db_client
    from api.services.crypto import CredentialEncryptionError, unseal_credential_data

    if organization_id is None:
        raise MissingCredentialError(
            "Cannot resolve an ElevenLabs credential without an organization"
        )

    credential = await db_client.get_provider_credential(organization_id, PROVIDER)
    if not credential:
        raise MissingCredentialError(
            f"Organization {organization_id} has no ElevenLabs credential. "
            "Add one under Settings → Voice provider."
        )

    try:
        data = unseal_credential_data(credential.credential_data)
    except CredentialEncryptionError as exc:
        # The message from the crypto layer is safe — it never echoes the
        # ciphertext or the key.
        raise MissingCredentialError(
            f"Organization {organization_id}'s ElevenLabs credential could not "
            f"be decrypted: {exc}"
        ) from exc

    api_key = (data or {}).get("api_key", "")
    if not api_key:
        raise MissingCredentialError(
            f"Organization {organization_id}'s ElevenLabs credential is empty."
        )

    return ElevenLabsClient(api_key=api_key, organization_id=organization_id)
