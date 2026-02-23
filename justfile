set dotenv-load := false

# Install both editable (dev) and wheel (global-like) versions
install:
  uv tool install --editable . --upgrade --reinstall
  uv build
  bash -c 'wheel="$(ls -t dist/atelier-*.whl | head -n1)"; version="${wheel##*/atelier-}"; version="${version%-py3-none-any.whl}"; uv tool install --find-links dist --prerelease=allow --reinstall "atelier==${version}"'
  uv tool update-shell

# Install globally from a built wheel (not tied to the working tree)
install-global:
  uv build
  bash -c 'wheel="$(ls -t dist/atelier-*.whl | head -n1)"; version="${wheel##*/atelier-}"; version="${version%-py3-none-any.whl}"; uv tool install --find-links dist --prerelease=allow --reinstall "atelier==${version}"'
  uv tool update-shell

# Install globally for day-to-day use (editable)
install-editable:
  uv tool install --editable . --upgrade --reinstall
  uv tool update-shell

# Editable install in a local venv
install-dev:
  uv venv
  uv pip install -e .[dev]

# Run the test suite
test:
  uv pip install -e .[dev]
  uv run python -m atelier.skill_frontmatter_validation
  uv run pytest
  bash tests/shell/run.sh

# Run integration evals (requires codex CLI on PATH)
test-integration:
  python evals/run-publish-skill-evals.py

# Run lint checks
lint:
  bash scripts/lint-gate.sh

# Run static type checks
typecheck:
  uv run --extra dev pyright

# Auto-format code
format:
  uv run ruff check --select I,RUF022 --fix .
  uv run ruff format .
  uv run --extra dev mdformat --wrap 80 .
