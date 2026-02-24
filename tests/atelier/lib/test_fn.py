from collections.abc import Iterator

from atelier.lib import apply


def test_apply_invokes_callback_for_each_item_in_order() -> None:
    seen: list[int] = []
    apply(seen.append, [1, 2, 3])
    assert seen == [1, 2, 3]


def test_apply_consumes_generators_eagerly() -> None:
    touched: list[int] = []

    def values() -> Iterator[int]:
        for value in (1, 2, 3):
            touched.append(value)
            yield value

    apply(lambda _item: None, values())
    assert touched == [1, 2, 3]
