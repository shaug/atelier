"""Executable contract for the first skill-based Atelier changeset."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_CAPABILITY = ROOT / "skills" / "atelier" / "references" / "host-capability.json"


class HostBoundaryContract(unittest.TestCase):
    """Define the missing capability that issue 774 must implement."""

    @unittest.expectedFailure
    def test_host_capability_is_published(self) -> None:
        """Require a versioned, fail-closed host capability descriptor."""
        payload = json.loads(HOST_CAPABILITY.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "atelier.host-capability/v1")
        self.assertEqual(payload["reference_host"], "codex")
        self.assertEqual(
            payload["delegated_capability"],
            "agent-scripts.implement-ticket/delegated-execution/v1",
        )
        self.assertEqual(payload["native_state_access"], "read-only")
        self.assertFalse(payload["fallback_to_copied_workflows"])


if __name__ == "__main__":
    unittest.main()
