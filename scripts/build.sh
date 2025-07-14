sh ./scripts/lint.sh
pytest
rm -rf dist
uv sync
uv build