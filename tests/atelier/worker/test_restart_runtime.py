from __future__ import annotations

import os
from pathlib import Path

from atelier.worker import restart_runtime


def test_capture_worker_relaunch_contract_prefers_orig_argv_and_subset_env(
    tmp_path: Path,
) -> None:
    contract = restart_runtime.capture_worker_relaunch_contract(
        argv=("atelier", "work", "--run-mode", "watch"),
        orig_argv=(
            "/venv/bin/python",
            "-m",
            "atelier.cli",
            "work",
            "--run-mode",
            "watch",
        ),
        env={
            "ATELIER_RUN_MODE": "watch",
            "BEADS_DIR": "/tmp/beads",
            "FOO": "bar",
            "HOME": "/Users/tester",
            "PATH": "/venv/bin:/usr/bin",
        },
        cwd=tmp_path,
        executable="/venv/bin/python",
    )

    assert contract.cwd == tmp_path
    assert contract.entry_kind == "module"
    assert contract.entry_value == "atelier.cli"
    assert contract.exec_target() == "/venv/bin/python"
    assert contract.exec_argv() == (
        "/venv/bin/python",
        "-m",
        "atelier.cli",
        "work",
        "--run-mode",
        "watch",
    )
    assert contract.exec_env() == {
        "ATELIER_RUN_MODE": "watch",
        "BEADS_DIR": "/tmp/beads",
        "PATH": "/venv/bin:/usr/bin",
    }


def test_capture_worker_startup_runtime_detects_package_tree_updates(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "atelier"
    module_path = package_root / "worker.py"
    package_root.mkdir()
    module_path.write_text("print('v1')\n", encoding="utf-8")

    startup = restart_runtime.capture_worker_startup_runtime(
        argv=("atelier", "work"),
        orig_argv=("/venv/bin/python", "-m", "atelier.cli", "work"),
        env={"PATH": "/venv/bin:/usr/bin"},
        cwd=tmp_path,
        executable="/venv/bin/python",
        version="1.2.3",
        package_root=package_root,
    )

    assert startup.startup_fingerprint.version == "1.2.3"
    assert startup.startup_fingerprint.code_marker_kind == "package-tree-stat-digest"
    assert startup.runtime_changed(version="1.2.3", package_root=package_root) is False

    stat = module_path.stat()
    module_path.write_text("print('v2 with changes')\n", encoding="utf-8")
    os.utime(module_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert startup.runtime_changed(version="1.2.3", package_root=package_root) is True
