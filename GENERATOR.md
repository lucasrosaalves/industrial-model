# CLI Generator

The `industrial-model` CLI generates a fully-typed Python client package directly from a live Cognite Data Fusion (CDF) data model. Each view in the data model becomes its own sub-client, filter class, and set of literal types—all wired together in a facade class you drop into your codebase.

---

## Installation

The generator requires optional dependencies. Install them with the `cli` extra:

```bash
pip install 'industrial-model[cli]'
```

---

## Commands

| Command | Purpose |
|---------|---------|
| `industrial_model generate` | Generate the typed client package from a data model |
| `industrial_model login` | Authenticate via browser and run the generator interactively |

---

## `generate`

Connects to CDF with an existing bearer token and writes the client package to disk.

### Flags

| Flag | Description |
|------|-------------|
| `--token` | CDF bearer token |
| `--client-id` | OAuth client ID for browser login (used when `--token` is omitted) |
| `--project` | CDF project name |
| `--base-url` | CDF base URL, e.g. `https://westeurope-1.cognitedata.com` |
| `--data-model` | Data model in `space/externalId/version` format |
| `--external-id` | Data model external ID (alternative to `--data-model`) |
| `--space` | Data model space (alternative to `--data-model`) |
| `--version` | Data model version (alternative to `--data-model`) |
| `--output-dir` / `--output` | Directory where the package is written |
| `--client-name` | Name of the generated facade class (default: `{ExternalId}Client`) |
| `--overwrite` | Replace the output directory if it already exists |
| `--no-input` | Disable interactive prompts; all required values must come from flags |

### Quick start

```bash
industrial_model generate \
  --token "$CDF_TOKEN" \
  --project my-cdf-project \
  --base-url https://westeurope-1.cognitedata.com \
  --data-model cdf_cdm/CogniteCore/v1 \
  --output ./generated \
  --client-name CogniteCoreClient
```

You can also specify the data model as three separate flags:

```bash
industrial_model generate \
  --token "$CDF_TOKEN" \
  --project my-cdf-project \
  --base-url https://westeurope-1.cognitedata.com \
  --space cdf_cdm \
  --external-id CogniteCore \
  --version v1
```

When flags are omitted the CLI prompts for each value interactively. Pass `--no-input` to skip prompts and fail fast if a required flag is missing.

---

## `login`

Opens a browser window for OAuth PKCE authentication, then runs the generator interactively: cluster, project, data model, client name, and output directory are all collected as prompts.

```bash
industrial_model login
```

Pass `--client-id` when your CDF tenant requires a specific OAuth application:

```bash
industrial_model login --client-id <your-oauth-client-id>
```

Pass `--org` to pre-fill the organization hint on the Cognite login page:

```bash
industrial_model login --org my-org
```

---

## Generated package layout

Running the generator for a data model with views `CogniteAsset` and `CogniteEquipment` and `--client-name CogniteCoreClient` produces:

```
generated/
├── __init__.py               # exports CogniteCoreClient
├── cognite_core_client.py    # facade class
├── models.py                 # all models re-exported
├── cognite_asset/
│   ├── __init__.py
│   ├── client.py             # CogniteAssetClient
│   ├── filters.py            # CogniteAssetFilter
│   ├── models.py             # CogniteAsset, CogniteAssetAggregation
│   └── types.py              # literal types for properties
└── cognite_equipment/
    ├── __init__.py
    ├── client.py
    ├── filters.py
    ├── models.py
    └── types.py
```

### File descriptions

| File | Contents |
|------|----------|
| `__init__.py` | Exports the facade class by name |
| `{client_module}.py` | Facade class; one attribute per view, each an instance of its view client |
| `models.py` | Re-exports all view models from the per-view packages |
| `{view}/models.py` | `{View}` (writable model) and `{View}Aggregation` (aggregation model) |
| `{view}/filters.py` | `{View}Filter` typed dict with one key per filterable property |
| `{view}/types.py` | Literal types: `{View}QueryProperty`, `{View}FilterProperty`, `{View}GroupByProperty`, `{View}AggregationProperty` |
| `{view}/client.py` | `{View}Client(ViewClient)` with typed overloads for every method |

---

## Next step

After generating a package, see [Generated Client Usage](GENERATED_CLIENT.md) for
client construction, rich query/filter examples, search, aggregations, mutations,
pagination, and async usage.

---

## How it works

1. **Fetch views** — connects to CDF and retrieves the inline-expanded views for the target data model.
2. **Build definitions** — maps each CDF property type to a Python type and resolves relation paths between views.
3. **Render templates** — Jinja2 templates produce the source files for the package.
4. **Format** — runs `ruff format` then `ruff check --fix` on the output directory so the generated code is always clean.

---

## Instance space filtering

When instance data lives in many spaces you can scope each view to specific spaces, reducing query overhead. Pass `--instance-spaces-config` (programmatic API) or configure it directly in `GeneratorConfig`:

```python
from industrial_model.cli.config import GeneratorConfig, InstanceSpaceConfig
from industrial_model.cli.generator import generate_from_views

config = GeneratorConfig.from_token(
    token="...",
    project="my-project",
    base_url="https://westeurope-1.cognitedata.com",
    client_name="CogniteCoreClient",
    output_path=Path("./generated"),
    data_model=DataModelId(space="cdf_cdm", external_id="CogniteCore", version="v1"),
)
config.instance_space_configs = [
    InstanceSpaceConfig(
        view_or_space_external_id="CogniteAsset",
        instance_spaces=["prod-space", "staging-space"],
    ),
]
generate_from_views(views, config)
```

`view_or_space_external_id` may be a view `external_id` or a space name; the generator applies the config to whichever views match.

---

## Programmatic API

You can call the generator from Python instead of the CLI:

```python
from pathlib import Path
from industrial_model.cli.config import GeneratorConfig
from industrial_model.cli.generator import generate
from industrial_model.config import DataModelId

config = GeneratorConfig.from_token(
    token="<bearer-token>",
    project="my-cdf-project",
    base_url="https://westeurope-1.cognitedata.com",
    client_name="CogniteCoreClient",
    output_path=Path("./generated"),
    data_model=DataModelId(
        space="cdf_cdm",
        external_id="CogniteCore",
        version="v1",
    ),
)

generate(config, overwrite=True)
```

`generate_from_views` is also available if you already have a list of `cognite.client.data_classes.data_modeling.View` objects:

```python
from industrial_model.cli.generator import generate_from_views

generate_from_views(views, config, overwrite=True)
```
