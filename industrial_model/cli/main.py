from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from industrial_model.config import DataModelId

from .auth import (
    DEFAULT_LOGIN_CONFIG,
    LoginConfig,
    LoginOptions,
    Session,
    browser_login,
    extract_auth_from_token,
    save_session,
)
from .config import GeneratorConfig
from .generator import generate as generate_client
from .helpers import to_pascal, to_snake

app = typer.Typer(
    add_completion=False,
    help="Industrial Model command line tools.",
    no_args_is_help=True,
)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        app(
            args=list(argv) if argv is not None else None,
            prog_name="industrial_model",
            standalone_mode=False,
        )
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    return 0


@app.callback()
def callback() -> None:
    """Industrial Model command line tools."""


@app.command("generate", help="Generate typed client classes from a CDF data model.")
def generate_command(
    token: Annotated[
        str | None,
        typer.Option("--token", help="CDF bearer token."),
    ] = None,
    client_id: Annotated[
        str,
        typer.Option("--client-id", help="OAuth client ID for browser login."),
    ] = DEFAULT_LOGIN_CONFIG.client_id,
    project: Annotated[
        str | None,
        typer.Option("--project", help="CDF project name."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="CDF base URL."),
    ] = None,
    data_model: Annotated[
        str | None,
        typer.Option(
            "--data-model",
            help='Data model identifier in "space/externalId/version" format.',
        ),
    ] = None,
    external_id: Annotated[
        str | None,
        typer.Option("--external-id", help="Data model external ID."),
    ] = None,
    space: Annotated[
        str | None,
        typer.Option("--space", help="Data model space."),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Data model version."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "--output", help="Output directory."),
    ] = None,
    client_name: Annotated[
        str | None,
        typer.Option("--client-name", help="Generated facade client name."),
    ] = None,
    json_types: Annotated[
        Path | None,
        typer.Option(
            "--json-types",
            help="Accepted for TypeScript CLI compatibility; currently ignored.",
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Replace the output directory if it already exists.",
        ),
    ] = False,
    no_input: Annotated[
        bool,
        typer.Option(
            "--no-input",
            help="Disable prompts and require values from flags.",
        ),
    ] = False,
) -> None:
    try:
        answers = _collect_generate_answers(
            token=token,
            client_id=client_id,
            project=project,
            base_url=base_url,
            data_model=data_model,
            external_id=external_id,
            space=space,
            version=version,
            output_dir=output_dir,
            client_name=client_name,
            no_input=no_input,
        )
        if json_types is not None:
            typer.echo(
                "--json-types is only used by the TypeScript generator; ignoring it.",
                err=True,
            )

        generator_config = GeneratorConfig.from_token(
            token=answers.token,
            project=answers.project,
            base_url=answers.base_url,
            client_name=answers.client_name,
            output_path=answers.output_dir,
            data_model=answers.data_model,
        )
        should_overwrite = overwrite
        if answers.output_dir.exists() and not should_overwrite:
            if no_input:
                raise FileExistsError(
                    f"Output directory {answers.output_dir} already exists. "
                    "Pass --overwrite to replace it."
                )
            should_overwrite = typer.confirm(
                f"Output directory {answers.output_dir} exists. Replace it?",
                default=False,
            )
            if not should_overwrite:
                typer.echo("Cancelled.")
                raise typer.Exit(1)

        generate_client(generator_config, overwrite=should_overwrite)
        typer.echo(f"Generated {answers.client_name} in {answers.output_dir}")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@dataclass
class GenerateAnswers:
    token: str
    project: str
    base_url: str
    client_name: str
    output_dir: Path
    data_model: DataModelId


def _collect_generate_answers(
    *,
    token: str | None,
    client_id: str,
    project: str | None,
    base_url: str | None,
    data_model: str | None,
    external_id: str | None,
    space: str | None,
    version: str | None,
    output_dir: Path | None,
    client_name: str | None,
    no_input: bool,
) -> GenerateAnswers:
    resolved_token = _prompt_token(token, client_id=client_id, no_input=no_input)
    extracted = extract_auth_from_token(resolved_token)
    resolved_project = _prompt_str(
        "CDF project name",
        project,
        extracted.project,
        no_input=no_input,
    )
    resolved_base_url = _prompt_str(
        "CDF base URL",
        base_url,
        extracted.base_url,
        no_input=no_input,
    )

    parsed_data_model = _parse_data_model(data_model) if data_model else None

    resolved_external_id = _prompt_str(
        "Data model external ID",
        parsed_data_model.external_id if parsed_data_model else external_id,
        None,
        no_input=no_input,
    )
    resolved_space = _prompt_str(
        "Data model space",
        parsed_data_model.space if parsed_data_model else space,
        None,
        no_input=no_input,
    )
    resolved_version = _prompt_str(
        "Data model version",
        parsed_data_model.version if parsed_data_model else version,
        None,
        no_input=no_input,
    )
    default_client_name = f"{to_pascal(resolved_external_id)}Client"
    resolved_client_name = _prompt_str(
        "Client class name",
        client_name,
        default_client_name,
        no_input=no_input,
    )
    resolved_output_dir = _prompt_path(
        "Output directory",
        output_dir,
        Path(to_snake(resolved_client_name)),
        no_input=no_input,
    )

    return GenerateAnswers(
        token=resolved_token,
        project=resolved_project,
        base_url=resolved_base_url,
        client_name=resolved_client_name,
        output_dir=resolved_output_dir,
        data_model=DataModelId(
            external_id=resolved_external_id,
            space=resolved_space,
            version=resolved_version,
        ),
    )


@app.command(
    "login",
    help="Authenticate with CDF and interactively select a data model.",
)
def login_command(
    client_id: Annotated[
        str,
        typer.Option("--client-id", help="OAuth client ID for browser login."),
    ] = DEFAULT_LOGIN_CONFIG.client_id,
    org: Annotated[
        str | None,
        typer.Option("--org", help="Organization hint for Cognite login."),
    ] = None,
) -> None:
    try:
        token = browser_login(LoginOptions(org=org), LoginConfig(client_id=client_id))
        extracted = extract_auth_from_token(token)
        cluster = typer.prompt("CDF cluster", default="az-phx-001")
        base_url = f"https://{cluster.strip()}.cognitedata.com"

        project = extracted.project or typer.prompt("CDF project name")

        selected = _prompt_data_model(token, project, base_url)
        dm_id = f"{selected.space}/{selected.external_id}/{selected.version}"
        save_session(Session(project=project, base_url=base_url, data_model=dm_id))

        default_client_name = f"{to_pascal(selected.external_id)}Client"
        client_name = typer.prompt("Client class name", default=default_client_name)
        output_dir = Path(
            typer.prompt("Output directory", default=to_snake(client_name))
        )

        overwrite = False
        if output_dir.exists():
            overwrite = typer.confirm(
                f"Output directory {output_dir} exists. Replace it?", default=False
            )
            if not overwrite:
                typer.echo("Cancelled.")
                raise typer.Exit(1)

        generator_config = GeneratorConfig.from_token(
            token=token,
            project=project,
            base_url=base_url,
            client_name=client_name,
            output_path=output_dir,
            data_model=DataModelId(
                space=selected.space,
                external_id=selected.external_id,
                version=selected.version,
            ),
        )
        generate_client(generator_config, overwrite=overwrite)
        typer.echo(f"Generated {client_name} in {output_dir}")
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def _prompt_data_model(token: str, project: str, base_url: str) -> Any:
    from cognite.client import ClientConfig, CogniteClient
    from cognite.client.credentials import Token

    client = CogniteClient(
        ClientConfig(
            client_name="industrial-model-generator",
            project=project,
            credentials=Token(token),
            base_url=base_url,
        )
    )

    typer.echo("\nFetching available data models...")
    data_models = sorted(
        client.data_modeling.data_models.list(limit=-1, include_global=True),
        key=lambda dm: (dm.space, dm.external_id, dm.version),
    )

    if not data_models:
        raise RuntimeError("No data models found in this CDF project.")

    identity = _prompt_data_model_identity(data_models)
    versions = _data_models_for_identity(data_models, identity)
    return _prompt_data_model_version(versions)


def _data_model_identity(data_model: Any) -> tuple[str, str]:
    return data_model.space, data_model.external_id


def _prompt_data_model_identity(data_models: Sequence[Any]) -> tuple[str, str]:
    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice

    identities = _data_model_identities(data_models)
    choices = [
        Choice(
            value=identity,
            name=f"{identity[0]}/{identity[1]}",
        )
        for identity in identities
    ]

    return cast(
        tuple[str, str],
        inquirer.fuzzy(  # type: ignore[attr-defined]
            message="Select data model:",
            choices=choices,
            max_height="50%",
        ).execute(),
    )


def _data_model_identities(data_models: Sequence[Any]) -> list[tuple[str, str]]:
    return sorted({_data_model_identity(dm) for dm in data_models})


def _data_models_for_identity(
    data_models: Sequence[Any], identity: tuple[str, str]
) -> list[Any]:
    return [dm for dm in data_models if _data_model_identity(dm) == identity]


def _prompt_data_model_version(data_models: Sequence[Any]) -> Any:
    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice

    choices = [
        Choice(
            value=i,
            name=f"{dm.version}"
            + (f" — {dm.name}" if getattr(dm, "name", None) else ""),
        )
        for i, dm in enumerate(data_models)
    ]

    index = inquirer.fuzzy(  # type: ignore[attr-defined]
        message="Select data model version:",
        choices=choices,
        max_height="50%",
    ).execute()

    return data_models[index]


def _prompt_token(
    token: str | None,
    *,
    client_id: str,
    no_input: bool,
) -> str:
    if token:
        return token
    if no_input:
        raise ValueError("Missing required value: CDF bearer token")

    method = typer.prompt(
        "Authentication method (browser/token)",
        default="browser",
    )
    if str(method).strip().lower() == "browser":
        org = typer.prompt("Organization hint", default="")
        return browser_login(
            LoginOptions(org=str(org) or None), LoginConfig(client_id=client_id)
        )
    return str(typer.prompt("CDF bearer token", hide_input=True))


def _parse_data_model(value: str) -> DataModelId:
    parts = value.split("/")
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            "Invalid --data-model format. Expected "
            f'"space/externalId/version", got "{value}"'
        )
    return DataModelId(space=parts[0], external_id=parts[1], version=parts[2])


def _prompt_str(
    label: str,
    value: str | None,
    default: str | None,
    *,
    no_input: bool,
) -> str:
    if value:
        return value
    if no_input:
        if default:
            return default
        raise ValueError(f"Missing required value: {label}")

    answer = (
        typer.prompt(label, default=default)
        if default is not None
        else typer.prompt(label)
    )
    return str(answer)


def _prompt_path(
    label: str,
    value: Path | None,
    default: Path,
    *,
    no_input: bool,
) -> Path:
    if value:
        return value
    if no_input:
        return default

    return Path(typer.prompt(label, default=str(default)))
