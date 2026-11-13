"""identity.py: Entra access tokens for the APIs, checked offline with a test key."""
import pytest

from sofibot_eqz import identity


def test_valid_token(entra_token):
    user = identity.from_bearer(entra_token(["Sofibot.Autor", "Ventas"]))
    assert user.email == "ana@empresa.test" and user.roles == ("Sofibot.Autor", "Ventas") and user.via == "entra"


@pytest.mark.parametrize("claims", [
    {"aud": "api://otra-app"},
    {"tid": "otro-tenant"},
    {"iss": "https://sts.windows.net/otro-tenant/"},
    {"exp": 1},
    {"scp": None},                      # an application's own token, not a user's
    {"preferred_username": None},
])
def test_rejected_tokens(entra_token, claims):
    with pytest.raises(identity.IdentityError):
        identity.from_bearer(entra_token(["Sofibot.Autor"], **claims))


def test_token_signed_by_another_key(entra_token):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(identity.IdentityError):
        identity.from_bearer(entra_token(["Sofibot.Autor"], key=other))


@pytest.mark.parametrize("header", ["", "Bearer ", "Basic abc", "Bearer not-a-jwt"])
def test_malformed_headers(entra_token, header):
    with pytest.raises(identity.IdentityError):
        identity.from_bearer(header)


def test_tables_from_roles():
    permissions = {"Ventas": {"gold.ventas"}, "Direccion": {"*"}}
    assert identity.Identity("a", roles=("Ventas",)).tables(permissions) == {"gold.ventas"}
    assert identity.Identity("a", roles=("Direccion",)).tables(permissions) is None
    assert identity.Identity("a", roles=("Otro",)).tables(permissions) == set()
    assert identity.Identity("token", via="token").tables(permissions) is None
