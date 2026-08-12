"""Abstract scaffolding for cloud asset sync. Connection CRUD and config
validation work now; actual discovery/apply are stubbed until the next
release, per the spec ("abstract scaffolding for sync to AWS and Azure,
with sync tools coming up in the next release")."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.crypto import decrypt_json, encrypt_json
from rain.db.tenant_models import SyncConnection


@dataclass
class DiscoveredAsset:
    external_id: str
    name: str
    attributes: dict[str, Any]


class SyncProvider(Protocol):
    provider_key: str

    def test_connection(self, config: dict[str, Any]) -> tuple[bool, str]: ...

    async def discover_assets(self, config: dict[str, Any]) -> list[DiscoveredAsset]: ...


class AWSProvider:
    provider_key = "aws"
    required_fields = ("role_arn", "region")

    def test_connection(self, config: dict[str, Any]) -> tuple[bool, str]:
        missing = [f for f in self.required_fields if not config.get(f)]
        if missing:
            return False, f"missing required fields: {', '.join(missing)}"
        return True, "configuration looks valid (live connectivity check ships in a future release)"

    async def discover_assets(self, config: dict[str, Any]) -> list[DiscoveredAsset]:
        raise NotImplementedError("AWS asset discovery is coming in the next release")


class AzureProvider:
    provider_key = "azure"
    required_fields = ("tenant_id", "client_id", "client_secret", "subscription_id")

    def test_connection(self, config: dict[str, Any]) -> tuple[bool, str]:
        missing = [f for f in self.required_fields if not config.get(f)]
        if missing:
            return False, f"missing required fields: {', '.join(missing)}"
        return True, "configuration looks valid (live connectivity check ships in a future release)"

    async def discover_assets(self, config: dict[str, Any]) -> list[DiscoveredAsset]:
        raise NotImplementedError("Azure asset discovery is coming in the next release")


PROVIDERS: dict[str, SyncProvider] = {"aws": AWSProvider(), "azure": AzureProvider()}


def connection_list_stmt():
    return select(SyncConnection).order_by(SyncConnection.name)


async def list_connections(db: AsyncSession) -> list[SyncConnection]:
    result = await db.execute(connection_list_stmt())
    return list(result.scalars())


async def create_connection(
    db: AsyncSession, *, provider: str, name: str, config: dict[str, Any]
) -> SyncConnection:
    connection = SyncConnection(provider=provider, name=name, config_encrypted=encrypt_json(config))
    db.add(connection)
    await db.commit()
    return connection


def decrypt_config(connection: SyncConnection) -> dict[str, Any]:
    return decrypt_json(connection.config_encrypted)
