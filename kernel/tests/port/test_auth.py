import time
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from fast_ddd_port.auth import JwtVerifier
from fast_ddd_port.problems import HttpProblem
from fast_ddd_port.settings import JwtSettings


@pytest.fixture
def settings() -> JwtSettings:
    return JwtSettings(
        issuer="https://issuer.test",
        audience="tests",
        jwks_url="https://issuer.test/keys",
        user_id_claim="sub",
        organization_id_claim="org",
        permissions_claim="scope",
        permissions_format="space_separated",
        leeway_seconds=0,
    )


class SigningKey:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = {
            **RSAAlgorithm.to_jwk(self.private.public_key(), as_dict=True),
            "kid": kid,
            "alg": "RS256",
            "use": "sig",
        }

    def token(
        self,
        settings: JwtSettings,
        overrides: Mapping[str, Any] | None = None,
        *,
        algorithm: str = "RS256",
    ) -> str:
        claims = {
            "iss": settings.issuer,
            "aud": settings.audience,
            "exp": int(time.time()) + 300,
            "sub": "user-1",
            "org": str(uuid4()),
            "scope": "invoice:read invoice:void",
            **(overrides or {}),
        }
        return jwt.encode(claims, self.private, algorithm=algorithm, headers={"kid": self.kid})


@pytest.fixture
def key() -> SigningKey:
    return SigningKey("original")


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "wrong"},
        {"aud": "wrong"},
        {"nbf": int(time.time()) + 3600},
        {"exp": int(time.time()) - 3600},
        {"exp": None},
        {"nbf": None},
        {"iat": None},
        {"sub": 12},
        {"sub": " "},
        {"org": "bad"},
        {"org": ""},
        {"org": []},
        {"scope": ["invoice:read"]},
        {"scope": {"invoice:read": True}},
        {"scope": 1},
    ],
)
async def test_invalid_signed_claims_are_rejected(
    settings: JwtSettings,
    key: SigningKey,
    overrides: dict[str, Any],
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"keys": [key.public]}))
    ) as client:
        with pytest.raises(HttpProblem) as raised:
            await JwtVerifier(settings, client).verify(key.token(settings, overrides))
    assert raised.value.status == 401
    assert 'error="invalid_token"' in raised.value.headers["WWW-Authenticate"]


@pytest.mark.parametrize("algorithm", ["RS256", "RS512"])
async def test_signature_and_algorithm_allowlist_are_enforced(
    settings: JwtSettings,
    key: SigningKey,
    algorithm: str,
) -> None:
    other = SigningKey(key.kid)
    signer = other if algorithm == "RS256" else key
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"keys": [key.public]}))
    ) as client:
        with pytest.raises(HttpProblem, match=r"auth\.token_invalid"):
            await JwtVerifier(settings, client).verify(signer.token(settings, algorithm=algorithm))


@pytest.mark.parametrize("permissions", ["invoice:read", [1], ["invoice:read", None], [""], {}])
async def test_list_permissions_reject_wrong_shapes(
    settings: JwtSettings,
    key: SigningKey,
    permissions: Any,
) -> None:
    settings.permissions_format = "list"
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"keys": [key.public]}))
    ) as client:
        with pytest.raises(HttpProblem, match=r"auth\.token_invalid"):
            await JwtVerifier(settings, client).verify(key.token(settings, {"scope": permissions}))


async def test_jwks_cache_refreshes_for_rotation_and_expiration(
    settings: JwtSettings,
    key: SigningKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rotated = SigningKey("rotated")
    keys = [key.public]
    calls: list[str] = []

    def fetch(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        return httpx2.Response(200, json={"keys": keys})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(fetch)) as client:
        verifier = JwtVerifier(settings, client)
        assert (await verifier.verify(key.token(settings))).permissions == {
            "invoice:read",
            "invoice:void",
        }
        await verifier.verify(key.token(settings))
        assert len(calls) == 1
        keys.append(rotated.public)
        await verifier.verify(rotated.token(settings))
        assert len(calls) == 2
        monkeypatch.setattr("fast_ddd_port.auth.time", SimpleNamespace(monotonic=lambda: 1e12))
        await verifier.verify(rotated.token(settings))
        assert len(calls) == 3
        with pytest.raises(HttpProblem, match=r"auth\.token_invalid"):
            await verifier.verify(SigningKey("absent").token(settings))
        assert len(calls) == 4


@pytest.mark.parametrize(
    ("permissions_format", "permissions"),
    [
        ("list", ["invoice:read", "invoice:void"]),
        ("space_separated", "invoice:read invoice:void"),
    ],
)
async def test_configured_permission_shapes_and_global_identity(
    settings: JwtSettings,
    key: SigningKey,
    permissions_format: str,
    permissions: Any,
) -> None:
    settings = settings.model_copy(update={"permissions_format": permissions_format})
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"keys": [key.public]}))
    ) as client:
        principal = await JwtVerifier(settings, client).verify(
            key.token(settings, {"org": None, "scope": permissions})
        )
    assert principal.organization_id is None
    assert principal.permissions == {"invoice:read", "invoice:void"}
