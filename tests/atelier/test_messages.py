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
