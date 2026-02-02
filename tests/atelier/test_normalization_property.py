from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

import atelier.git as git
import atelier.workspace as workspace

WHITESPACE = " \t\r\n"
SEGMENT_CHARS = string.ascii_letters + string.digits + "-._"
HOST_CHARS = string.ascii_letters + string.digits + "-."
PATH_CHARS = string.ascii_letters + string.digits + "-_."


def _strip_git_suffix(path: str) -> str:
    normalized = path.strip().rstrip("/")
    if normalized.lower().endswith(".git"):
        return normalized[: -len(".git")]
    return normalized


segment_strategy = st.text(
    alphabet=SEGMENT_CHARS,
    min_size=1,
    max_size=10,
).filter(lambda value: value != "..")

host_strategy = st.text(
    alphabet=HOST_CHARS,
    min_size=1,
    max_size=20,
)

path_segment_strategy = st.text(
    alphabet=PATH_CHARS,
    min_size=1,
    max_size=12,
)

path_strategy = st.lists(path_segment_strategy, min_size=1, max_size=4).map("/".join)


@st.composite
def safe_workspace_names(draw: st.DrawFn) -> str:
    segments = draw(st.lists(segment_strategy, min_size=1, max_size=4))
    separators = draw(
        st.lists(
            st.sampled_from(["/", "\\"]),
            min_size=len(segments) - 1,
            max_size=len(segments) - 1,
        )
    )
    parts: list[str] = []
    for index, segment in enumerate(segments):
        parts.append(segment)
        if index < len(separators):
            parts.append(separators[index])
    name = "".join(parts)
    prefix = draw(st.text(alphabet=WHITESPACE, max_size=3))
    suffix = draw(st.text(alphabet=WHITESPACE, max_size=3))
    return f"{prefix}{name}{suffix}"


@st.composite
def absolute_workspace_names(draw: st.DrawFn) -> str:
    prefix = draw(st.text(alphabet=WHITESPACE, max_size=3))
    lead = draw(st.sampled_from(["/", "\\"]))
    tail = draw(st.text(alphabet=SEGMENT_CHARS + "/\\", max_size=12))
    suffix = draw(st.text(alphabet=WHITESPACE, max_size=3))
    return f"{prefix}{lead}{tail}{suffix}"


@st.composite
def dotdot_workspace_names(draw: st.DrawFn) -> str:
    before = draw(st.lists(segment_strategy, max_size=2))
    after = draw(st.lists(segment_strategy, max_size=2))
    segments = [*before, "..", *after]
    separators = draw(
        st.lists(
            st.sampled_from(["/", "\\"]),
            min_size=len(segments) - 1,
            max_size=len(segments) - 1,
        )
    )
    parts: list[str] = []
    for index, segment in enumerate(segments):
        parts.append(segment)
        if index < len(separators):
            parts.append(separators[index])
    name = "".join(parts)
    prefix = draw(st.text(alphabet=WHITESPACE, max_size=3))
    suffix = draw(st.text(alphabet=WHITESPACE, max_size=3))
    return f"{prefix}{name}{suffix}"


@given(name=safe_workspace_names())
def test_normalize_workspace_name_round_trip(name: str) -> None:
    normalized = workspace.normalize_workspace_name(name)
    expected = name.strip().replace("\\", "/")
    assert normalized == expected
    assert "\\" not in normalized
    assert not normalized.startswith("/")


@given(name=absolute_workspace_names())
def test_normalize_workspace_name_rejects_absolute_paths(name: str) -> None:
    with pytest.raises(SystemExit):
        workspace.normalize_workspace_name(name)


@given(name=dotdot_workspace_names())
def test_normalize_workspace_name_rejects_dotdot_segments(name: str) -> None:
    with pytest.raises(SystemExit):
        workspace.normalize_workspace_name(name)


@given(
    host=host_strategy,
    path=path_strategy,
    suffix=st.sampled_from(["", ".git", ".GIT"]),
    prefix=st.text(alphabet=WHITESPACE, max_size=2),
    suffix_space=st.text(alphabet=WHITESPACE, max_size=2),
)
def test_normalize_origin_url_scp(
    host: str,
    path: str,
    suffix: str,
    prefix: str,
    suffix_space: str,
) -> None:
    raw = f"{prefix}git@{host}:{path}{suffix}{suffix_space}"
    expected_path = _strip_git_suffix(f"{path}{suffix}")
    assert git.normalize_origin_url(raw) == f"{host.lower()}/{expected_path}"


@given(
    host=host_strategy,
    path=path_strategy,
    suffix=st.sampled_from(["", ".git", ".GIT"]),
    prefix=st.text(alphabet=WHITESPACE, max_size=2),
    suffix_space=st.text(alphabet=WHITESPACE, max_size=2),
)
def test_normalize_origin_url_https(
    host: str,
    path: str,
    suffix: str,
    prefix: str,
    suffix_space: str,
) -> None:
    raw = f"{prefix}https://{host}/{path}{suffix}{suffix_space}"
    expected_path = _strip_git_suffix(f"{path}{suffix}")
    assert git.normalize_origin_url(raw) == f"{host.lower()}/{expected_path}"
