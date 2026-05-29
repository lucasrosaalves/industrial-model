import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cognite.client import ClientConfig, CogniteClient
from cognite.client.credentials import Token
from cognite.client.data_classes.data_modeling import View

from .config import GeneratorConfig, InstanceSpaceConfig
from .definitions import ViewDefinition, resolve_all_relation_paths
from .helpers import to_snake


def generate(config: GeneratorConfig, *, overwrite: bool = False) -> None:
    views = _get_views(config)
    generate_from_views(views, config, overwrite=overwrite)


def generate_from_views(
    views: Sequence[View], config: GeneratorConfig, *, overwrite: bool = False
) -> None:
    view_definitions = resolve_all_relation_paths(
        _get_view_definitions(views, config.instance_space_configs)
    )
    output_path = config.output_path
    _prepare_output_path(output_path, overwrite=overwrite)

    _write_package_files(
        output_path,
        view_definitions=view_definitions,
        client_name=config.client_name,
    )
    _format_output_path(output_path)


def _get_views(config: GeneratorConfig) -> list[View]:
    cognite_client = _create_cognite_client(config)
    data_model = cognite_client.data_modeling.data_models.retrieve(
        ids=config.data_model.as_tuple(), inline_views=True
    )
    return data_model.latest_version().views


def _create_cognite_client(config: GeneratorConfig) -> CogniteClient:
    if not config.token or not config.project or not config.base_url:
        raise ValueError("Token, project, and base URL are required")

    return CogniteClient(
        ClientConfig(
            client_name="industrial-model-generator",
            project=config.project,
            credentials=Token(config.token),
            base_url=config.base_url,
        )
    )


def _get_view_definitions(
    views: Sequence[View], instance_space_configs: Sequence[InstanceSpaceConfig]
) -> list[ViewDefinition]:
    instance_space_configs_as_dict = {
        instance_space_config.view_or_space_external_id: instance_space_config
        for instance_space_config in instance_space_configs
    }
    view_definitions = [
        ViewDefinition.from_view(
            view,
            instance_space_configs_as_dict.get(view.external_id)
            or instance_space_configs_as_dict.get(view.space),
        )
        for view in sorted(views, key=lambda view: view.external_id)
    ]
    return view_definitions


def _prepare_output_path(output_path: Path, *, overwrite: bool) -> None:
    if output_path.exists():
        if not output_path.is_dir():
            raise NotADirectoryError(f"Output path {output_path} is not a directory")
        if not overwrite:
            raise FileExistsError(
                f"Output directory {output_path} already exists. "
                "Pass --overwrite to replace it."
            )
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)


def _write_package_files(
    output_path: Path,
    *,
    view_definitions: Sequence[ViewDefinition],
    client_name: str,
) -> None:
    env = _create_jinja_environment()
    paths = {
        "__init__.j2": output_path / "__init__.py",
        "clients_facade.j2": output_path / f"{to_snake(client_name)}.py",
        "models.j2": output_path / "models.py",
    }
    (output_path / "py.typed").touch()

    context = {
        "view_definitions": view_definitions,
        "client_name": client_name,
        "client_module_name": to_snake(client_name),
    }
    for template_name, path in paths.items():
        path.write_text(
            env.get_template(template_name).render(context), encoding="utf-8"
        )

    for view_definition in view_definitions:
        view_path = output_path / view_definition.view_module_name
        view_path.mkdir(parents=True)
        view_context = {**context, "view_definition": view_definition}
        for template_name, filename in {
            "view_init.j2": "__init__.py",
            "view_models.j2": "models.py",
            "view_filters.j2": "filters.py",
            "view_types.j2": "types.py",
            "view_specific_client.j2": "client.py",
        }.items():
            (view_path / filename).write_text(
                env.get_template(template_name).render(view_context),
                encoding="utf-8",
            )


def _create_jinja_environment() -> Any:
    try:
        from jinja2 import Environment, PackageLoader
    except ImportError as exc:
        raise RuntimeError(
            "The generator CLI requires optional dependencies. "
            "Install them with: pip install 'industrial-model[cli]'"
        ) from exc

    return Environment(
        loader=PackageLoader("industrial_model.cli", "templates"),
        autoescape=False,
        keep_trailing_newline=True,
    )


def _format_output_path(output_path: Path) -> None:
    _run_ruff(["format", str(output_path)])
    _run_ruff(["check", "--fix", str(output_path)])
    _run_ruff(["format", str(output_path)])


def _run_ruff(args: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return

    details = "\n".join(
        item for item in (result.stdout.strip(), result.stderr.strip()) if item
    )
    raise RuntimeError(f"Ruff failed while formatting generated code:\n{details}")
