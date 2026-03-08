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
