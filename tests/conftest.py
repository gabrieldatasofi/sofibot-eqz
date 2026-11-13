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
    monkeypatch.setenv("SOFIBOT_QUERY_DATA", str(tmp_path / "consultas"))
    (tmp_path / "reports").mkdir()
    return tmp_path


TENANT, CLIENT = "tenant-id", "client-id"


@pytest.fixture(scope="session")
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def entra_token(signing_key, monkeypatch):
    """Builds Entra-like access tokens signed by a test key that identity.py trusts."""
    import time

    import jwt

    from sofibot_eqz import identity

    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    monkeypatch.setenv("ENTRA_CLIENT_ID", CLIENT)
    monkeypatch.setattr(identity, "_signing_key", lambda token, settings: signing_key.public_key())

    def make(roles=(), email="ana@empresa.test", key=None, **claims):
        now = int(time.time())
        payload = {"aud": f"api://{CLIENT}", "iss": f"https://sts.windows.net/{TENANT}/", "tid": TENANT,
                   "iat": now, "exp": now + 600, "scp": "access_as_user", "preferred_username": email,
                   "name": "Ana", "roles": list(roles), **claims}
        payload = {k: v for k, v in payload.items() if v is not None}
        return "Bearer " + jwt.encode(payload, key or signing_key, algorithm="RS256")

    return make
