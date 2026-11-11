"""한국어 답변을 재생 단위 문장으로 나누는 순수 함수."""

from __future__ import annotations

import re

MIN_CHARS = 10  # 이보다 짧은 조각은 다음 조각에 붙인다 (마지막 조각이면 앞 조각에)
MAX_CHARS = 150  # 이보다 길면 MAX_CHARS 이내 마지막 ", " 또는 " "에서 자른다 (반복)

_BOUNDARY = re.compile(r"(?<=[.?!。])\s+")


def _split_long(piece: str) -> list[str]:
    out: list[str] = []
    rest = piece
    while len(rest) > MAX_CHARS:
        window = rest[: MAX_CHARS + 1]
        idx = window.rfind(", ")
        if idx > 0:
            head, tail = rest[: idx + 1], rest[idx + 2 :]
        else:
            idx = window.rfind(" ")
            if idx <= 0:
                break
            head, tail = rest[:idx], rest[idx + 1 :]
        head, tail = head.strip(), tail.strip()
        if not head or not tail:
            break
        out.append(head)
        rest = tail
    out.append(rest)
    return out


def split_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    pieces: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        pieces.extend(p.strip() for p in _BOUNDARY.split(line) if p.strip())
    merged: list[str] = []
    buf = ""
    for p in pieces:
        buf = f"{buf} {p}" if buf else p
        if len(buf) >= MIN_CHARS or len(pieces) == 1:
            merged.append(buf)
            buf = ""
    if buf:
        if merged:
            merged[-1] = f"{merged[-1]} {buf}"
        else:
            merged.append(buf)

    result: list[str] = []
    for m in merged:
        result.extend(_split_long(m))
    return result
