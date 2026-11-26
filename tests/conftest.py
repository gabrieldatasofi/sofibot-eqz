import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def folders(tmp_path, monkeypatch):
    from sofibot_eqz import config

    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "DRAFTS_DIR", tmp_path / "reports" / ".borradores")
    monkeypatch.setattr(config, "ACCESS_DIR", tmp_path / "acceso")
    monkeypatch.setenv("SOFIBOT_QUERY_DATA", str(tmp_path / "consultas"))
    (tmp_path / "reports").mkdir()
    return tmp_path


TENANT, CLIENT = "tenant-id", "client-id"


def grant(email, roles):
    """Give a user roles in acceso/usuarios.json, as an administrator would (Entra only signs in)."""
    import json

    from sofibot_eqz import config

    path = config.ACCESS_DIR / "usuarios.json"
    users = json.loads(path.read_text())["usuarios"] if path.is_file() else {}
    users[email] = list(roles)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"usuarios": users}))


@pytest.fixture(scope="session")
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def entra_token(signing_key, monkeypatch, tmp_path):
    """Builds Entra-like access tokens signed by a test key that identity.py trusts.

    Entra only says who the user is: the roles given here go to acceso/usuarios.json.
    """
    import time

    import jwt

    from sofibot_eqz import config, identity

    monkeypatch.setattr(config, "ACCESS_DIR", tmp_path / "acceso")

    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    monkeypatch.setenv("ENTRA_CLIENT_ID", CLIENT)
    monkeypatch.setattr(identity, "_signing_key", lambda token, settings: signing_key.public_key())

    def make(roles=(), email="ana@empresa.test", key=None, entra_roles=None, **claims):
        if email:
            grant(email, roles)
        now = int(time.time())
        payload = {"aud": f"api://{CLIENT}", "iss": f"https://sts.windows.net/{TENANT}/", "tid": TENANT,
                   "iat": now, "exp": now + 600, "scp": "access_as_user", "preferred_username": email,
                   "name": "Ana", "roles": entra_roles, **claims}
        payload = {k: v for k, v in payload.items() if v is not None}
        return "Bearer " + jwt.encode(payload, key or signing_key, algorithm="RS256")

    return make
