"""Qwen(OpenAI 호환 DashScope) 스트리밍 LLM. 실패·짧은 출력이면 FAQ 원문으로 폴백."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from collections.abc import Callable, Iterator
from typing import IO, cast

from app.pipeline.sentences import split_sentences
from app.pipeline.stubs import FALLBACK_ANSWER
from app.pipeline.types import FaqItem

log = logging.getLogger(__name__)

MIN_ANSWER_CHARS = 10
MAX_SENTENCES = 3

SYSTEM_PROMPT = (
    "당신은 민원 안내 음성 상담원입니다. 주어진 근거에 없는 내용은 말하지 마십시오. "
    "1~3문장의 존댓말로 답하고, 숫자와 기관명은 근거 원문 그대로 쓰십시오. "
    "목록이나 마크다운 기호는 쓰지 마십시오."
)

_BOUNDARY = re.compile(r"(?<=[.?!。])\s+")

Opener = Callable[[urllib.request.Request, float], IO[bytes]]


def _default_opener(req: urllib.request.Request, timeout: float) -> IO[bytes]:
    return cast(IO[bytes], urllib.request.urlopen(req, timeout=timeout))


class QwenLLM:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float,
        opener: Opener | None = None,
    ) -> None:
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._timeout_s = timeout_s
        self._opener = opener or _default_opener

    def answer(self, query: str, context: list[FaqItem]) -> str:
        if not context:
            return FALLBACK_ANSWER
        return " ".join(self.stream_sentences(query, context))

    def _request(self, query: str, top: FaqItem) -> urllib.request.Request:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"질문: {query}\n근거({top.id}): {top.answer}"},
            ],
            "stream": True,
            "max_tokens": 160,
            "temperature": 0.2,
            "enable_thinking": False,
        }
        return urllib.request.Request(
            self._url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

    def _deltas(self, query: str, top: FaqItem) -> Iterator[str]:
        resp = self._opener(self._request(query, top), self._timeout_s)
        try:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                choices = json.loads(data).get("choices") or []
                if choices:
                    content = (choices[0].get("delta") or {}).get("content")
                    if content:
                        yield content
        finally:
            resp.close()

    def stream_sentences(self, query: str, context: list[FaqItem]) -> Iterator[str]:
        if not context:
            yield FALLBACK_ANSWER
            return
        top = context[0]
        emitted = 0
        buf = ""
        try:
            for delta in self._deltas(query, top):
                buf += delta
                parts = _BOUNDARY.split(buf)
                # 마지막 조각은 아직 끝나지 않았을 수 있다
                done, buf = parts[:-1], parts[-1]
                pending = ""
                for p in done:
                    pending = f"{pending} {p.strip()}".strip()
                    if len(pending) < MIN_ANSWER_CHARS:
                        continue
                    yield pending
                    pending = ""
                    emitted += 1
                    if emitted >= MAX_SENTENCES:
                        return
                if pending:
                    buf = f"{pending} {buf}" if buf else pending
        except (OSError, ValueError, AttributeError) as exc:  # 네트워크·타임아웃·HTTP·파싱 오류
            log.warning("qwen llm failed: %s", type(exc).__name__)
            buf = ""
        tail = buf.strip()
        if emitted:
            if tail and emitted < MAX_SENTENCES:
                yield tail
            return
        if len(tail) < MIN_ANSWER_CHARS:
            yield from split_sentences(top.answer)
            return
        yield from split_sentences(tail)[:MAX_SENTENCES]
