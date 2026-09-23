import time
from types import SimpleNamespace
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from ted_procurement_mcp.oauth_auth import OwnerOAuthVerifier, ISSUER, RESOURCE


@pytest.fixture
def signed():
    private = ec.generate_private_key(ec.SECP256R1())
    verifier = OwnerOAuthVerifier("dedicated-client", "owner@example.com")
    verifier.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key()))
    claims = dict(iss=ISSUER, aud=RESOURCE, sub="owner-id", iat=int(time.time()),
                  exp=int(time.time()) + 300, client_id="dedicated-client", role="authenticated")
    return verifier, private, claims


def test_valid_resource_and_client(signed):
    verifier, private, claims = signed
    assert verifier.decode(jwt.encode(claims, private, algorithm="ES256"))["sub"] == "owner-id"


@pytest.mark.parametrize("field,value", [
    ("aud", "authenticated"), ("iss", "https://attacker.invalid"),
    ("client_id", "different-client"), ("role", "service_role"),
    ("exp", 1), ("is_anonymous", True),
])
def test_reject_wrong_identity_or_destination(signed, field, value):
    verifier, private, claims = signed
    claims[field] = value
    with pytest.raises((jwt.PyJWTError, ValueError)):
        verifier.decode(jwt.encode(claims, private, algorithm="ES256"))


def test_reject_bad_signature(signed):
    verifier, _, claims = signed
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.decode(jwt.encode(claims, other, algorithm="ES256"))
