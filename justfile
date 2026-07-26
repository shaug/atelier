set shell := ["bash", "-euo", "pipefail", "-c"]

validate:
    python3 scripts/validate_repository.py

lint: validate
    python3 -m compileall -q scripts contract_tests

test: validate
    python3 -m unittest discover -s contract_tests -v
    python3 experiments/mailbox_protocol_v0.py
