"""붙여넣은 텍스트와 FAQ CSV를 지식 조각(Chunk)으로 바꾸는 순수 함수."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Literal, cast

from app.agents.models import Chunk
from app.pipeline.sentences import split_sentences

CHUNK_TARGET_CHARS = 400
CHUNK_MAX_CHARS = 600
TITLE_MAX_CHARS = 40

KnowledgeErrorCode = Literal["knowledge_empty", "knowledge_too_large", "knowledge_bad_csv"]

_TERMINAL = (".", "?", "!", "。", "…")
_HEADERS = (("질문", "답변"), ("question", "answer"))


@dataclass(frozen=True)
class KnowledgeWarning:
    code: str  # "empty_row" | "duplicate_question" | "extra_columns"
    message: str


class KnowledgeError(ValueError):
    code: KnowledgeErrorCode

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = cast(KnowledgeErrorCode, code)
        self.message = message


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _is_heading(line: str) -> bool:
    return line.startswith("#") or (len(line) <= TITLE_MAX_CHARS and not line.endswith(_TERMINAL))


def _hard_cut(s: str) -> list[str]:
    return [s[i : i + CHUNK_MAX_CHARS] for i in range(0, len(s), CHUNK_MAX_CHARS)]


def _pieces(paragraph: str) -> list[str]:
    if len(paragraph) <= CHUNK_MAX_CHARS:
        return [paragraph]
    out: list[str] = []
    for sent in split_sentences(paragraph):
        out.extend(_hard_cut(sent) if len(sent) > CHUNK_MAX_CHARS else [sent])
    return out


def _pack(paragraphs: list[str]) -> list[str]:
    bodies: list[str] = []
    buf = ""
    for para in paragraphs:
        pieces = _pieces(para)
        sep = "\n" if len(pieces) == 1 else " "
        for i, piece in enumerate(pieces):
            join = "\n" if i == 0 else sep
            if buf and (len(buf) >= CHUNK_TARGET_CHARS or len(buf) + 1 + len(piece) > CHUNK_MAX_CHARS):
                bodies.append(buf)
                buf = ""
            buf = f"{buf}{join}{piece}" if buf else piece
    if buf:
        bodies.append(buf)
    return bodies


def _title_of(body: str) -> str:
    sents = split_sentences(body)
    first = sents[0] if sents else body
    return first[:TITLE_MAX_CHARS]


def chunk_text(text: str, max_chars: int) -> tuple[list[Chunk], list[KnowledgeWarning]]:
    if len(text) > max_chars:
        raise KnowledgeError("knowledge_too_large", f"텍스트는 {max_chars}자까지 넣을 수 있습니다")
    # (heading, paragraphs) 묶음
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    para: list[str] = []

    def flush_para() -> None:
        if para:
            sections[-1][1].append(" ".join(para))
            para.clear()

    for raw in text.replace("\ufeff", "").splitlines():
        line = _norm(raw)
        if not line:
            flush_para()
            continue
        if _is_heading(line):
            flush_para()
            sub = _norm(line.lstrip("#"))
            if sub:
                sections.append((sub, []))
            continue
        para.append(line)
    flush_para()

    chunks: list[Chunk] = []
    for heading, paragraphs in sections:
        if not paragraphs and heading is None:
            continue
        # 본문 없는 소제목도 버리지 않는다
        bodies = _pack(paragraphs) if paragraphs else [heading or ""]
        for body in bodies:
            title = heading if heading is not None else _title_of(body)
            chunks.append(
                Chunk(
                    chunk_id=f"c-{len(chunks) + 1:03d}",
                    title=title,
                    text=body,
                    index_text=f"{title}\n{body}",
                    origin="text",
                )
            )
    if not chunks:
        raise KnowledgeError("knowledge_empty", "지식으로 쓸 내용이 없습니다")
    return chunks, []


def parse_faq_csv(
    csv_text: str, max_rows: int, max_chars: int
) -> tuple[list[Chunk], list[KnowledgeWarning]]:
    if len(csv_text) > max_chars:
        raise KnowledgeError("knowledge_too_large", f"CSV는 {max_chars}자까지 넣을 수 있습니다")
    text = csv_text.lstrip("\ufeff")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as e:
        raise KnowledgeError("knowledge_bad_csv", f"CSV를 읽을 수 없습니다: {e}") from e

    warnings: list[KnowledgeWarning] = []
    start = 0
    if rows and len(rows[0]) >= 2:
        head = (rows[0][0].strip().lower(), rows[0][1].strip().lower())
        if head in _HEADERS:
            start = 1

    pairs: list[tuple[int, str, str]] = []
    extra_warned = False
    for lineno, row in enumerate(rows[start:], start=start + 1):
        if len(row) > 2 and not extra_warned and any(c.strip() for c in row[2:]):
            warnings.append(KnowledgeWarning("extra_columns", "앞 두 열(질문, 답변)만 사용합니다"))
            extra_warned = True
        q = _norm(row[0]) if row else ""
        a = row[1].strip() if len(row) > 1 else ""
        if not q or not a:
            warnings.append(KnowledgeWarning("empty_row", f"{lineno}행: 질문 또는 답변이 비어 있어 건너뜁니다"))
            continue
        pairs.append((lineno, q, a))

    if len(pairs) > max_rows:
        raise KnowledgeError("knowledge_too_large", f"CSV는 {max_rows}행까지 넣을 수 있습니다")

    chunks: list[Chunk] = []
    seen: set[str] = set()
    for lineno, q, a in pairs:
        key = q.casefold()
        if key in seen:
            warnings.append(
                KnowledgeWarning("duplicate_question", f"{lineno}행: 같은 질문이 있어 첫 행만 씁니다")
            )
            continue
        seen.add(key)
        chunks.append(
            Chunk(chunk_id=f"q-{len(chunks) + 1:03d}", title=q, text=a, index_text=q, origin="faq_csv")
        )
    if not chunks:
        raise KnowledgeError("knowledge_empty", "CSV에 쓸 수 있는 질문·답변 행이 없습니다")
    return chunks, warnings
