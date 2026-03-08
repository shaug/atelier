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
  bash scripts/supported-python.sh venv
  env -u VIRTUAL_ENV uv pip install -e .[dev]

# Run the test suite
test:
  bash scripts/supported-python.sh venv
  env -u VIRTUAL_ENV uv pip install -e .[dev]
  bash scripts/supported-python.sh run python -m atelier.skill_frontmatter_validation
  bash scripts/supported-python.sh run pytest
  bash tests/shell/run.sh

# Run integration evals (requires codex CLI on PATH)
test-integration:
  python evals/run-publish-skill-evals.py

# Run lint checks
lint:
  bash scripts/lint-gate.sh

# Run static type checks
typecheck:
  bash scripts/supported-python.sh run --extra dev pyright

# Auto-format code
format:
  bash scripts/supported-python.sh run ruff check --select I,RUF022 --fix .
  bash scripts/supported-python.sh run ruff format .
  bash scripts/supported-python.sh run --extra dev mdformat --wrap 80 .
