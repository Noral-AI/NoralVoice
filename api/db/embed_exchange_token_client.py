"""Database client for one-shot iframe-auth exchange tokens.

The exchange-token flow: an external integration (NoralOS plugin) hits
``POST /embed/exchange-token`` authenticated as itself, gets back an
opaque single-use token, and embeds the resulting URL in an iframe. The
user's browser hits ``GET /embed-login?token=…&path=…`` which validates
+ consumes the token, sets a session cookie, and redirects into the
target page.

Phase 1 stages just this contract so integrators can wire against a
stable API early; Phase 4 builds the iframe surface on top.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import EmbedExchangeTokenModel


def hash_exchange_token(plaintext: str) -> str:
    """SHA-256 hex of the plaintext token.

    We hash before storage so a DB read can't recover the plaintext.
    SHA-256 (not bcrypt) is appropriate: tokens are high-entropy
    (`secrets.token_urlsafe(32)`), short-lived, and single-use, so an
    adversary with DB read access can't grind hashes faster than they
    can use a still-valid token directly.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


class EmbedExchangeTokenClient(BaseDBClient):
    async def create_embed_exchange_token(
        self,
        token_hash: str,
        organization_id: int,
        target_user_id: int,
        target_path: str,
        ttl_seconds: int,
    ) -> EmbedExchangeTokenModel:
        """Insert a new exchange token row.

        The caller has already generated the plaintext token and SHA-256
        hash; we just persist. ``expires_at`` is computed from
        ``ttl_seconds`` (which the caller has already clamped).
        """
        async with self.async_session() as session:
            now = datetime.now(UTC)
            row = EmbedExchangeTokenModel(
                token_hash=token_hash,
                organization_id=organization_id,
                target_user_id=target_user_id,
                target_path=target_path,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            session.add(row)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            await session.refresh(row)
        return row

    async def consume_embed_exchange_token(
        self, token_hash: str
    ) -> Optional[EmbedExchangeTokenModel]:
        """Atomic single-use consumption.

        Returns the row only if the token exists, isn't expired, and
        isn't already consumed. The row's ``consumed_at`` is set inside
        the same transaction so two parallel consumers can't both win.
        Uses ``SELECT … FOR UPDATE`` against the row to serialize, which
        is fine because the table is small and reads are rare per token.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(EmbedExchangeTokenModel)
                .where(EmbedExchangeTokenModel.token_hash == token_hash)
                .with_for_update()
            )
            row = result.scalars().first()
            if row is None:
                return None

            now = datetime.now(UTC)
            if row.consumed_at is not None:
                return None
            if row.expires_at <= now:
                return None

            row.consumed_at = now
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            await session.refresh(row)
        return row
