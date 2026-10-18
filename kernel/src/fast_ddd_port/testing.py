"""Test helpers for services: signed JWTs that the kernel's verifier accepts offline."""

import time
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from fast_ddd_port.auth import JwtVerifier
from fast_ddd_port.settings import JwtSettings

TEST_KEY_ID = "test-key"


class TokenFactory:
    """Signs RS256 tokens shaped by ``settings`` (issuer, audience, claim names)."""

    def __init__(self, settings: JwtSettings) -> None:
        self.settings = settings
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        self.jwks: dict[str, Any] = {
            "keys": [{**public, "kid": TEST_KEY_ID, "alg": "RS256", "use": "sig"}]
        }

    def verifier(self) -> JwtVerifier:
        """A verifier whose JWKS comes from this factory instead of the network."""
        transport = httpx2.MockTransport(lambda _: httpx2.Response(200, json=self.jwks))
        return JwtVerifier(self.settings, httpx2.AsyncClient(transport=transport))

    def token(
        self,
        *,
        organization_id: UUID | None,
        permissions: Sequence[str] = (),
        user_id: str = "user-1",
        expires_in: int = 300,
    ) -> str:
        settings = self.settings
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": settings.issuer,
            "aud": settings.audience,
            settings.user_id_claim: user_id,
            settings.organization_id_claim: str(organization_id) if organization_id else None,
            settings.permissions_claim: (
                " ".join(permissions)
                if settings.permissions_format == "space_separated"
                else list(permissions)
            ),
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": TEST_KEY_ID})

    def authorization(
        self,
        *,
        organization_id: UUID | None,
        permissions: Sequence[str] = (),
        user_id: str = "user-1",
        expires_in: int = 300,
    ) -> dict[str, str]:
        token = self.token(
            organization_id=organization_id,
            permissions=permissions,
            user_id=user_id,
            expires_in=expires_in,
        )
        return {"Authorization": f"Bearer {token}"}
