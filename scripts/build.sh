sh ./scripts/lint.sh
uv run pytest
rm -rf dist
uv sync
uv build