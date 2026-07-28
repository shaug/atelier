"""Generate strict UUIDv7 identifiers for Atelier mailbox documents."""

from __future__ import annotations

import secrets
import time

SUPPORTED_PREFIXES = frozenset({"clm", "ini", "msg", "prj", "rcp", "run", "wrk"})


def new_identifier(prefix: str) -> str:
    """Return one lowercase UUIDv7 identifier with an Atelier prefix."""
    if prefix not in SUPPORTED_PREFIXES:
        supported = ", ".join(sorted(SUPPORTED_PREFIXES))
        raise ValueError(
            f"unsupported Atelier identifier prefix {prefix!r}; expected one of {supported}"
        )
    milliseconds = int(time.time() * 1000)
    if milliseconds >= 1 << 48:
        raise ValueError("current time exceeds the UUIDv7 timestamp range")
    random_bits = secrets.randbits(74)
    value = milliseconds << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    hexadecimal = f"{value:032x}"
    uuid = (
        f"{hexadecimal[:8]}-{hexadecimal[8:12]}-{hexadecimal[12:16]}-"
        f"{hexadecimal[16:20]}-{hexadecimal[20:]}"
    )
    return f"{prefix}_{uuid}"
