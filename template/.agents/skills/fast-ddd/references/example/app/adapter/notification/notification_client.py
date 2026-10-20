from collections.abc import Mapping
from uuid import UUID

import httpx2
from fast_ddd.serialization import JsonValue


class NotificationClient:
    """The notification service. ``PUT`` by a caller-chosen key makes every send idempotent."""

    def __init__(self, http: httpx2.AsyncClient) -> None:
        self._http = http

    async def send(
        self, key: str, *, organization_id: UUID, kind: str, data: Mapping[str, JsonValue]
    ) -> None:
        response = await self._http.put(
            f"/notifications/{key}",
            json={"organizationId": str(organization_id), "kind": kind, "data": dict(data)},
        )
        response.raise_for_status()
