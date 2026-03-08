import atelier.messages as messages


def test_render_and_parse_message_roundtrip() -> None:
    metadata = {
        "from": "atelier/worker/alice",
        "cc": ["atelier/worker/bob", "atelier/worker/eve"],
        "reply_to": None,
    }
    body = "Hello there"
    rendered = messages.render_message(metadata, body)
    parsed = messages.parse_message(rendered)
    assert parsed.metadata == metadata
    assert parsed.body == body


def test_render_and_parse_message_roundtrip_with_boolean_metadata() -> None:
    metadata = {
        "thread": "at-epic.1",
        "blocking": True,
        "reply_to": None,
    }

    rendered = messages.render_message(metadata, "Review this before starting")
    parsed = messages.parse_message(rendered)

    assert parsed.metadata == metadata


def test_parse_message_without_frontmatter() -> None:
    payload = messages.parse_message("No frontmatter here\n")
    assert payload.metadata == {}
    assert payload.body == "No frontmatter here\n"


def test_parse_message_contract_normalizes_work_threaded_metadata() -> None:
    rendered = messages.render_message(
        {
            "from": "atelier/planner/codex/p1",
            "thread": "at-ue6aj.1",
            "audience": ["worker"],
            "kind": "instruction",
            "blocking": True,
        },
        "Apply the requested change.",
    )

    contract = messages.parse_message_contract(
        rendered,
        assignee="atelier/worker/codex/p2",
    )

    assert contract.sender == "atelier/planner/codex/p1"
    assert contract.delivery == "work-threaded"
    assert contract.thread_id == "at-ue6aj.1"
    assert contract.thread_kind == "changeset"
    assert contract.audience == ("worker",)
    assert contract.kind == "instruction"
    assert contract.blocking is True


def test_build_message_contract_preserves_legacy_agent_addressed_metadata() -> None:
    contract = messages.build_message_contract(
        {"from": "atelier/planner/codex/p1", "msg_type": "notification"},
        assignee="atelier/worker/codex/p2",
    )

    assert contract.delivery == "agent-addressed"
    assert contract.kind == "notification"
    assert contract.audience == ("worker",)
    assert contract.thread_id is None


def test_build_message_contract_preserves_explicit_epic_thread_kind() -> None:
    contract = messages.build_message_contract(
        {
            "from": "atelier/planner/codex/p1",
            "thread": "at-ue6aj",
            "thread_kind": "epic",
        },
        assignee="atelier/worker/codex/p2",
    )

    assert contract.delivery == "work-threaded"
    assert contract.thread_id == "at-ue6aj"
    assert contract.thread_kind == "epic"


def test_message_blocks_worker_for_threaded_worker_assignment() -> None:
    issue = {
        "id": "at-msg-1",
        "title": "Worker handoff",
        "assignee": "atelier/worker/codex/p100",
        "description": messages.render_message(
            {"from": "atelier/planner/codex/p200", "thread": "at-epic.1"},
            "Resolve the review follow-up before coding.",
        ),
    }

    assert messages.message_blocks_runtime(
        issue,
        runtime_role="worker",
        thread_ids={"at-epic.1"},
    )
    assert not messages.message_blocks_runtime(
        issue,
        runtime_role="planner",
        thread_ids={"at-epic.1"},
    )


def test_message_blocks_planner_for_threaded_needs_decision_queue() -> None:
    issue = {
        "id": "at-msg-2",
        "title": "NEEDS-DECISION: Root branch conflict (at-epic)",
        "description": messages.render_message(
            {
                "from": "atelier/worker/codex/p100",
                "queue": "planner",
                "thread": "at-epic",
                "msg_type": "notification",
            },
            "Pick a different root branch.",
        ),
    }

    assert messages.message_blocks_runtime(
        issue,
        runtime_role="planner",
        thread_ids={"at-epic"},
    )
    assert not messages.message_blocks_runtime(
        issue,
        runtime_role="worker",
        thread_ids={"at-epic"},
    )
