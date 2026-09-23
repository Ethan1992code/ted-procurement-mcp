"""Strict single-owner verification for a dedicated Supabase OAuth client."""
from __future__ import annotations

import os
import httpx
import jwt
from starlette.concurrency import run_in_threadpool

RESOURCE = "https://ted-procurement-mcp.vercel.app/mcp"
ISSUER = "https://tpbzknktxuodulcxencf.supabase.co/auth/v1"
PUBLISHABLE_KEY = "sb_publishable_fdqGcmseceLNU3GuoLV6fg_0kBsTOtY"


class OwnerOAuthVerifier:
    def __init__(self, client_id: str, owner_email: str):
        self.client_id = client_id
        self.owner_email = owner_email.lower()
        self.jwks = jwt.PyJWKClient(ISSUER + "/.well-known/jwks.json", timeout=10)

    def decode(self, token: str) -> dict:
        key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["ES256", "RS256"],
                            audience=RESOURCE, issuer=ISSUER,
                            options={"require": ["exp", "iat", "sub", "aud", "iss", "client_id"]})
        if not self.client_id or claims.get("client_id") != self.client_id:
            raise ValueError("wrong_client")
        if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
            raise ValueError("wrong_role")
        return claims

    async def verify(self, token: str) -> bool:
        if not self.client_id or not self.owner_email or len(token) > 16000:
            return False
        try:
            claims = await run_in_threadpool(self.decode, token)
            # The user's current verified email comes from Auth, never editable metadata.
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(ISSUER + "/user", headers={
                    "apikey": PUBLISHABLE_KEY, "Authorization": "Bearer " + token})
            if response.status_code != 200:
                return False
            user = response.json()
            return bool(user.get("id") == claims["sub"]
                        and user.get("email", "").lower() == self.owner_email
                        and user.get("email_confirmed_at")
                        and not user.get("is_anonymous"))
        except (jwt.PyJWTError, httpx.HTTPError, ValueError, KeyError, TypeError):
            return False


def verifier_from_env():
    client_id = os.getenv("MCP_OAUTH_CLIENT_ID", "").strip()
    owner = os.getenv("MCP_OAUTH_OWNER_EMAIL", "").strip()
    return OwnerOAuthVerifier(client_id, owner) if client_id and owner else None
