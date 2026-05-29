import base64
import json
import urllib.parse
from pathlib import Path

from industrial_model.cli.auth import (
    LoginConfig,
    Session,
    _build_authorization_url,
    decode_token_claims,
    extract_auth_from_token,
    load_session,
    save_session,
)


def test_extract_auth_from_token_reads_project_and_base_url() -> None:
    token = _jwt(
        {
            "projects": ["my-project"],
            "aud": "https://az-eastus-1.cognitedata.com",
        }
    )

    extracted = extract_auth_from_token(token)

    assert extracted.project == "my-project"
    assert extracted.base_url == "https://az-eastus-1.cognitedata.com"


def test_decode_token_claims_returns_empty_dict_for_invalid_token() -> None:
    assert decode_token_claims("not-a-jwt") == {}


def test_build_authorization_url_uses_client_id() -> None:
    url = _build_authorization_url(
        LoginConfig(client_id="custom-client-id"),
        {"authorization_endpoint": "https://auth.example.com/authorize"},
        "verifier",
        "state",
        "my-org",
    )

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    assert query["client_id"] == ["custom-client-id"]
    assert query["organization_hint"] == ["my-org"]


def test_save_session_creates_directory(tmp_path: Path) -> None:
    config = LoginConfig(cert_dir=tmp_path / "missing" / "auth")
    session = Session(
        project="my-project",
        base_url="https://az-eastus-1.cognitedata.com",
        data_model="cdf_cdm/CogniteCore/v1",
    )

    save_session(session, config)

    assert load_session(config) == session


def _jwt(payload: dict[str, object]) -> str:
    return ".".join(
        [
            _base64_url({"alg": "none"}),
            _base64_url(payload),
            "signature",
        ]
    )


def _base64_url(value: dict[str, object]) -> str:
    raw = json.dumps(value).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
