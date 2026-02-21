import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.sessions as sessions_mod


class TestFindCodexSession:
    def test_returns_most_recent_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".codex" / "sessions"
            sessions.mkdir(parents=True)

            target = "atelier:01TEST:feat-demo"
            older = sessions / "session-old.json"
            newer = sessions / "session-new.json"

            older.write_text(
                json.dumps({"messages": [{"role": "user", "content": target}]}),
                encoding="utf-8",
            )
            newer.write_text(
                json.dumps({"messages": [{"role": "user", "content": target}]}),
                encoding="utf-8",
            )

            now = os.path.getmtime(newer)
            os.utime(older, (now - 100, now - 100))

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo")

            assert session == "session-new"

    def test_ignores_prefix_overlaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".codex" / "sessions"
            sessions.mkdir(parents=True)

            target = "atelier:01TEST:feat-demo"
            exact = sessions / "session-exact.json"
            overlap = sessions / "session-overlap.json"

            exact.write_text(
                json.dumps({"messages": [{"role": "user", "content": target}]}),
                encoding="utf-8",
            )
            overlap.write_text(
                json.dumps(
                    {
                        "messages": [
                            {"role": "user", "content": f"{target}-extra"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            now = os.path.getmtime(overlap)
            os.utime(exact, (now - 100, now - 100))

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo")

            assert session == "session-exact"

    def test_returns_session_id_from_jsonl_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".codex" / "sessions" / "2026" / "01" / "14"
            sessions.mkdir(parents=True)

            target = "atelier:01TEST:feat-demo"
            session_id = "019bbe1b-1c3c-7ef0-b7e6-61477c74ceb1"
            session_file = sessions / f"rollout-2026-01-14T12-03-26-{session_id}.jsonl"

            session_file.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "instructions": "agent instructions",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "agent preamble"},
                            ],
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": target,
                            "images": [],
                            "local_images": [],
                            "text_elements": [],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo")

            assert session == session_id

    def test_reads_session_id_after_other_jsonl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_id = "019bbe1b-1c3c-7ef0-b7e6-61477c74ceb1"
            session_file = Path(tmp) / "session.jsonl"
            session_file.write_text(
                json.dumps({"type": "response_item", "payload": {"type": "noop"}})
                + "\n"
                + json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"id": session_id},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            assert sessions_mod.read_session_id(session_file) == session_id

    def test_respects_workspace_uid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".codex" / "sessions"
            sessions.mkdir(parents=True)

            target = "atelier:01TEST:feat-demo"
            workspace_uid = "uid-123"
            legacy = sessions / "session-legacy.json"
            legacy.write_text(
                json.dumps({"messages": [{"role": "user", "content": target}]}),
                encoding="utf-8",
            )

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo", workspace_uid)

            assert session is None

            uid_target = f"{target}:{workspace_uid}"
            uid_session = sessions / "session-uid.json"
            uid_session.write_text(
                json.dumps({"messages": [{"role": "user", "content": uid_target}]}),
                encoding="utf-8",
            )

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo", workspace_uid)

            assert session == "session-uid"
