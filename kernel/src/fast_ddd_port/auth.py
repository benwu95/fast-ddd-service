import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import httpx2
import jwt
from fastapi import Depends
from fastapi.params import Depends as DependsParam

from fast_ddd.context import User
from fast_ddd_port.problems import HttpProblem
from fast_ddd_port.settings import JwtSettings

_INVALID = 'Bearer error="invalid_token"'


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    organization_id: UUID | None
    permissions: frozenset[str]
    claims: Mapping[str, Any]


class JwksCache:
    """Signing keys by ``kid``; refetched when expired or when an unknown ``kid`` shows up."""

    def __init__(self, url: str, client: httpx2.AsyncClient, max_age_seconds: int) -> None:
        self._url = url
        self._client = client
        self._max_age = max_age_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0

    async def key_for(self, kid: str) -> jwt.PyJWK | None:
        expired = time.monotonic() - self._fetched_at > self._max_age
        if expired or kid not in self._keys:
            await self._refresh()
        return self._keys.get(kid)

    async def _refresh(self) -> None:
        response = await self._client.get(self._url, timeout=5.0)
        response.raise_for_status()
        key_set = jwt.PyJWKSet.from_dict(cast(dict[str, Any], response.json()))
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id}
        self._fetched_at = time.monotonic()


class JwtVerifier:
    def __init__(self, settings: JwtSettings, client: httpx2.AsyncClient) -> None:
        self._settings = settings
        self._jwks = JwksCache(settings.jwks_url, client, settings.jwks_cache_seconds)

    async def verify(self, token: str) -> Principal:
        settings = self._settings
        try:
            header = jwt.get_unverified_header(token)
            key = await self._jwks.key_for(str(header.get("kid", "")))
            if key is None:
                raise HttpProblem("auth.token_invalid", headers={"WWW-Authenticate": _INVALID})
            claims = jwt.decode(
                token,
                key=key,
                algorithms=settings.algorithms,
                audience=settings.audience,
                issuer=settings.issuer,
                leeway=settings.leeway_seconds,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise HttpProblem(
                "auth.token_expired", headers={"WWW-Authenticate": _INVALID}
            ) from error
        except jwt.InvalidTokenError as error:
            raise HttpProblem(
                "auth.token_invalid", headers={"WWW-Authenticate": _INVALID}
            ) from error
        return self._principal(claims)

    def _principal(self, claims: Mapping[str, Any]) -> Principal:
        settings = self._settings
        user_id = claims.get(settings.user_id_claim)
        raw_organization = claims.get(settings.organization_id_claim)
        if not isinstance(user_id, str) or not user_id.strip():
            raise HttpProblem("auth.token_invalid", headers={"WWW-Authenticate": _INVALID})
        if raw_organization is not None and not isinstance(raw_organization, str):
            raise HttpProblem("auth.token_invalid", headers={"WWW-Authenticate": _INVALID})
        try:
            organization_id = UUID(raw_organization) if raw_organization is not None else None
        except ValueError as error:
            raise HttpProblem(
                "auth.token_invalid", headers={"WWW-Authenticate": _INVALID}
            ) from error
        raw_permissions = claims.get(settings.permissions_claim)
        if settings.permissions_format == "space_separated":
            if raw_permissions is not None and not isinstance(raw_permissions, str):
                raise HttpProblem("auth.token_invalid", headers={"WWW-Authenticate": _INVALID})
            permissions = frozenset((raw_permissions or "").split())
        else:
            if raw_permissions is not None and (
                not isinstance(raw_permissions, list)
                or any(
                    not isinstance(p, str) or not p.strip()
                    for p in cast(list[Any], raw_permissions)
                )
            ):
                raise HttpProblem("auth.token_invalid", headers={"WWW-Authenticate": _INVALID})
            permissions = frozenset(cast(list[str], raw_permissions or []))
        name = claims.get("name")
        return Principal(
            user=User(id=user_id, name=name if isinstance(name, str) else None),
            organization_id=organization_id,
            permissions=permissions,
            claims=claims,
        )


_principal: ContextVar[Principal | None] = ContextVar("fast_ddd_principal", default=None)


def current_principal() -> Principal:
    principal = _principal.get()
    if principal is None:
        raise HttpProblem("auth.unauthenticated", headers={"WWW-Authenticate": "Bearer"})
    return principal


@contextmanager
def principal_scope(principal: Principal) -> Generator[Principal]:
    token = _principal.set(principal)
    try:
        yield principal
    finally:
        _principal.reset(token)


def require(permission: str) -> DependsParam:
    """Route dependency: 403 unless the token grants ``permission`` (``<aggregate>:<action>``)."""

    def check() -> None:
        if permission not in current_principal().permissions:
            raise HttpProblem("auth.permission_denied", detail=f"missing permission {permission}")

    return Depends(check)
