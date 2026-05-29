import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from industrial_model.cli.auth import DEFAULT_LOGIN_CONFIG
from industrial_model.cli.main import (
    _collect_generate_answers,
    _data_model_identities,
    _data_models_for_identity,
    _parse_data_model,
    app,
)

runner = CliRunner()


def test_collect_generate_answers_accepts_typescript_cli_flags() -> None:
    answers = _collect_generate_answers(
        token=_jwt(
            {
                "projects": ["my-project"],
                "aud": "https://az-eastus-1.cognitedata.com",
            }
        ),
        client_id=DEFAULT_LOGIN_CONFIG.client_id,
        project=None,
        base_url=None,
        data_model="cdf_cdm/CogniteCore/v1",
        external_id=None,
        space=None,
        version=None,
        output_dir=Path("generated"),
        client_name=None,
        no_input=True,
    )

    assert answers.token is not None
    assert answers.project == "my-project"
    assert answers.base_url == "https://az-eastus-1.cognitedata.com"
    assert answers.data_model.space == "cdf_cdm"
    assert answers.data_model.external_id == "CogniteCore"
    assert answers.data_model.version == "v1"
    assert answers.client_name == "CogniteCoreClient"
    assert answers.output_dir == Path("generated")


def test_parse_data_model_requires_space_external_id_and_version() -> None:
    with pytest.raises(ValueError, match="Invalid --data-model format"):
        _parse_data_model("cdf_cdm/CogniteCore")


def test_generate_help_does_not_include_config_option() -> None:
    result = runner.invoke(app, ["generate", "--help"])

    assert result.exit_code == 0
    assert "--config" not in result.output
    assert "--token" in result.output


def test_data_model_selection_groups_versions_by_space_and_external_id() -> None:
    core_v1 = SimpleNamespace(space="cdf_cdm", external_id="CogniteCore", version="v1")
    core_v2 = SimpleNamespace(space="cdf_cdm", external_id="CogniteCore", version="v2")
    wind_v1 = SimpleNamespace(space="wind", external_id="WindCore", version="v1")
    data_models = [core_v2, wind_v1, core_v1]

    assert _data_model_identities(data_models) == [
        ("cdf_cdm", "CogniteCore"),
        ("wind", "WindCore"),
    ]
    assert _data_models_for_identity(data_models, ("cdf_cdm", "CogniteCore")) == [
        core_v2,
        core_v1,
    ]


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
