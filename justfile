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
  uv run pytest

# Run lint checks
lint:
  uv run ruff check .
  uv run mdformat --check --wrap 80 .

# Auto-format code
format:
  uv run ruff check --select I,RUF022 --fix .
  uv run ruff format .
  uv run mdformat --wrap 80 .
