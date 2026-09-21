import importlib.metadata
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from pprint import pformat
from typing import Any
from urllib.parse import urlparse

from cognite.client import ClientConfig, CogniteClient
from cognite.client.credentials import Token
from cognite.client.data_classes.data_modeling import View

from industrial_model.cognite_adapters.view_mapper import (
    collect_new_dependency_view_ids,
)
from industrial_model.config import DataModelId

from .config import GeneratorConfig, InstanceSpaceConfig
from .definitions import ViewDefinition, resolve_all_relation_paths
from .helpers import to_snake

_RESERVED_PACKAGE_MODULES = frozenset(
    {"clients", "filters", "models", "types", "view_mapper"}
)


def generate(config: GeneratorConfig, *, overwrite: bool = False) -> None:
    cognite_client = _create_cognite_client(config)
    views = _get_views(cognite_client, config.data_model)
    cache_views = sorted(
        (
            _include_dependency_views(cognite_client, views)
            if config.view_mapper_cache
            else views
        ),
        key=lambda view: (view.external_id, view.space),
    )
    generate_from_views(views, config, overwrite=overwrite, cache_views=cache_views)


def generate_from_views(
    views: Sequence[View],
    config: GeneratorConfig,
    *,
    overwrite: bool = False,
    cache_views: Sequence[View] | None = None,
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
        data_model=config.data_model,
        cluster=_extract_cluster(config.base_url),
        view_mapper_cache=config.view_mapper_cache,
        cache_views=cache_views or views,
    )
    _format_output_path(output_path)


def _get_views(cognite_client: CogniteClient, data_model: DataModelId) -> list[View]:
    retrieved = cognite_client.data_modeling.data_models.retrieve(
        ids=data_model.as_tuple(), inline_views=True
    )
    return list(retrieved.latest_version().views)


def _include_dependency_views(
    cognite_client: CogniteClient, views: Sequence[View]
) -> list[View]:
    expanded: list[View] = list(views)
    while True:
        new_dependency_view_ids = collect_new_dependency_view_ids(expanded)
        if not new_dependency_view_ids:
            break
        expanded.extend(
            cognite_client.data_modeling.views.retrieve(ids=new_dependency_view_ids)
        )
    return expanded


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
    data_model: DataModelId,
    cluster: str | None,
    view_mapper_cache: bool,
    cache_views: Sequence[View],
) -> None:
    facade_module_name = to_snake(client_name)
    if facade_module_name in _RESERVED_PACKAGE_MODULES:
        raise ValueError(
            f"Client name {client_name!r} generates module "
            f"{facade_module_name!r}, which is reserved for generated package "
            "files. Pass a different --client-name."
        )

    env = _create_jinja_environment()
    paths = {
        "__init__.j2": output_path / "__init__.py",
        "clients_facade.j2": output_path / f"{facade_module_name}.py",
        "models.j2": output_path / "models.py",
        "filters.j2": output_path / "filters.py",
        "types.j2": output_path / "types.py",
        "clients.j2": output_path / "clients.py",
    }
    if view_mapper_cache:
        paths["view_mapper_cache.j2"] = output_path / "view_mapper.py"
    (output_path / "py.typed").touch()

    context = {
        "view_definitions": view_definitions,
        "client_name": client_name,
        "client_module_name": to_snake(client_name),
        "data_model_external_id": repr(data_model.external_id),
        "data_model_space": repr(data_model.space),
        "data_model_version": repr(data_model.version),
        "default_cluster": repr(cluster),
        "view_mapper_cache": view_mapper_cache,
        "view_dumps": (
            pformat([view.dump() for view in cache_views], width=70, sort_dicts=False)
            if view_mapper_cache
            else "[]"
        ),
        "header_data_model": _header_data_model(data_model),
        "generated_at": _generated_at(),
        "package_version": _package_version(),
        "used_filter_types": sorted(
            {ft for view in view_definitions for ft in view.used_filter_types}
        ),
    }
    for template_name, path in paths.items():
        path.write_text(
            env.get_template(template_name).render(context), encoding="utf-8"
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


def _header_data_model(data_model: DataModelId) -> str:
    version_label = (
        data_model.version
        if data_model.version.startswith("v")
        else f"v{data_model.version}"
    )
    return f"{data_model.space}/{data_model.external_id} {version_label}"


def _generated_at() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _package_version() -> str:
    try:
        return importlib.metadata.version("industrial-model")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _extract_cluster(base_url: str | None) -> str | None:
    if base_url is None:
        return None

    hostname = urlparse(base_url).hostname
    if hostname is None:
        return None

    cognite_suffix = ".cognitedata.com"
    if hostname.endswith(cognite_suffix):
        cluster = hostname[: -len(cognite_suffix)]
        return cluster or None

    return None


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
