set dotenv-load := false

# Install globally for day-to-day use
install:
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
