from typing import Any, Dict, List, Optional

from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import OrganizationConfigurationModel
from api.enums import OrganizationConfigurationKey
from api.services.crypto import seal_credential_data, unseal_credential_data

#: Keys whose value carries credential material and must be encrypted at rest.
#:
#: This is selective rather than blanket because the table is a general-purpose
#: key/value store: disposition mappings and call limits are not secrets, and
#: sealing them would mean decrypting every row on every scan while making the
#: values opaque to any query that inspects them.
SECRET_BEARING_KEYS: frozenset[str] = frozenset(
    {
        OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value,
        OrganizationConfigurationKey.TWILIO_CONFIGURATION.value,
        OrganizationConfigurationKey.LANGFUSE_CREDENTIALS.value,
    }
)


def _seal_if_secret(key: str, value: Any) -> Any:
    """Seal a configuration value if its key carries credential material."""
    if key in SECRET_BEARING_KEYS and isinstance(value, dict):
        return seal_credential_data(value)
    return value


def unseal_configuration_value(value: Any) -> Any:
    """Return a configuration value in the clear, sealed or not.

    Safe to call on every value regardless of key: non-sealed values pass
    through untouched, so callers do not have to know which keys are secrets.
    """
    if isinstance(value, dict):
        return unseal_credential_data(value)
    return value


class OrganizationConfigurationClient(BaseDBClient):
    async def get_configuration(
        self, organization_id: int, key: str
    ) -> Optional[OrganizationConfigurationModel]:
        """Get a specific configuration for an organization by key."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            return result.scalars().first()

    async def get_all_configurations(
        self, organization_id: int
    ) -> list[OrganizationConfigurationModel]:
        """Get all configurations for an organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id
                )
            )
            return result.scalars().all()

    async def upsert_configuration(
        self, organization_id: int, key: str, value: Any
    ) -> OrganizationConfigurationModel:
        """Create or update a configuration for an organization.

        Values under a secret-bearing key are sealed before they reach the
        database; everything else is stored as-is. See SECRET_BEARING_KEYS for
        why this is selective rather than blanket.
        """
        value = _seal_if_secret(key, value)

        async with self.async_session() as session:
            # First try to get existing configuration
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            config = result.scalars().first()

            if config:
                # Update existing configuration
                config.value = value
            else:
                # Create new configuration
                config = OrganizationConfigurationModel(
                    organization_id=organization_id,
                    key=key,
                    value=value,
                )
                session.add(config)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(config)
            return config

    async def delete_configuration(self, organization_id: int, key: str) -> bool:
        """Delete a configuration for an organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key == key,
                )
            )
            config = result.scalars().first()

            if not config:
                return False

            await session.delete(config)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            return True

    async def get_configuration_value(
        self, organization_id: int, key: str, default: Any = None
    ) -> Any:
        """Get the value of a configuration, returning default if not found."""
        config = await self.get_configuration(organization_id, key)
        return unseal_configuration_value(config.value) if config else default

    async def get_all_configurations_by_key(self, key: str) -> list[dict[str, Any]]:
        """Get all organization configurations for a given key.

        Returns a list of dicts with organization_id and the config value.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.key == key,
                )
            )
            return [
                {
                    "organization_id": config.organization_id,
                    "value": unseal_configuration_value(config.value),
                }
                for config in result.scalars().all()
                if config.value
            ]

    async def get_configurations_by_provider(
        self, key: str, provider: str
    ) -> List[Dict[str, Any]]:
        """Get all organization configurations for a given key filtered by provider.

        Returns a list of dicts with organization_id and the config value.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationConfigurationModel).where(
                    OrganizationConfigurationModel.key == key,
                )
            )
            configs = result.scalars().all()

            # Unsealed before the provider test, not after: a sealed value has
            # no "provider" key of its own, so filtering on the raw column
            # would silently match nothing once these rows are encrypted.
            unsealed = (
                (config.organization_id, unseal_configuration_value(config.value))
                for config in configs
                if config.value
            )

            return [
                {"organization_id": organization_id, "value": value}
                for organization_id, value in unsealed
                if isinstance(value, dict) and value.get("provider") == provider
            ]
