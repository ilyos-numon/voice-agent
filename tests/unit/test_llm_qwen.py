import io
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import IO

from app.pipeline.llm_qwen import MAX_SENTENCES, QwenLLM
from app.pipeline.sentences import split_sentences
from app.pipeline.stubs import FALLBACK_ANSWER
from app.pipeline.types import FaqItem

CTX = [FaqItem(id="faq-001", question="여권 재발급?", answer="여권 재발급은 민원실에서 합니다. 수수료는 5만원입니다.", source="s")]


def _sse(chunks: list[str]) -> bytes:
    lines = []
    for c in chunks:
        payload = {"choices": [{"delta": {"content": c}}]}
        lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


class FakeOpener:
    def __init__(self, body: bytes | None = None, exc: BaseException | None = None) -> None:
        self.body, self.exc = body, exc
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def __call__(self, req: urllib.request.Request, timeout: float) -> IO[bytes]:
        self.requests.append((req, timeout))
        if self.exc is not None:
            raise self.exc
        assert self.body is not None
        return io.BytesIO(self.body)


def _llm(op: FakeOpener) -> QwenLLM:
    return QwenLLM(api_key="k", base_url="http://fake/v1", model="m", timeout_s=3.0, opener=op)


def test_two_sentences_streamed_and_request_body() -> None:
    op = FakeOpener(_sse(["여권 재발급은 민원", "실에서 하십시오. 수수료는 ", "5만원입니다."]))
    out = list(_llm(op).stream_sentences("여권?", CTX))
    assert out == ["여권 재발급은 민원실에서 하십시오.", "수수료는 5만원입니다."]
    req, timeout = op.requests[0]
    assert timeout == 3.0
    assert req.full_url == "http://fake/v1/chat/completions"
    body = json.loads(req.data)  # type: ignore[arg-type]
    assert body["stream"] is True and body["max_tokens"] == 160
    assert body["temperature"] == 0.2 and body["enable_thinking"] is False
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == f"질문: 여권?\n근거(faq-001): {CTX[0].answer}"


def test_answer_joins_with_space() -> None:
    op = FakeOpener(_sse(["첫 번째 문장입니다. ", "두 번째 문장입니다."]))
    assert _llm(op).answer("q", CTX) == "첫 번째 문장입니다. 두 번째 문장입니다."


def test_four_sentences_truncated_to_three() -> None:
    op = FakeOpener(_sse(["가나다라마바사 일. ", "가나다라마바사 이. ", "가나다라마바사 삼. ", "가나다라마바사 사."]))
    out = list(_llm(op).stream_sentences("q", CTX))
    assert len(out) == MAX_SENTENCES
    assert out[-1] == "가나다라마바사 삼."


def test_connection_error_falls_back() -> None:
    op = FakeOpener(exc=urllib.error.URLError("refused"))
    assert list(_llm(op).stream_sentences("q", CTX)) == split_sentences(CTX[0].answer)


def test_timeout_falls_back() -> None:
    op = FakeOpener(exc=TimeoutError("timed out"))
    assert list(_llm(op).stream_sentences("q", CTX)) == split_sentences(CTX[0].answer)


def test_non_200_falls_back() -> None:
    err = urllib.error.HTTPError("http://fake", 500, "err", None, None)  # type: ignore[arg-type]
    op = FakeOpener(exc=err)
    assert list(_llm(op).stream_sentences("q", CTX)) == split_sentences(CTX[0].answer)


def test_short_output_falls_back() -> None:
    op = FakeOpener(_sse(["네."]))
    assert list(_llm(op).stream_sentences("q", CTX)) == split_sentences(CTX[0].answer)


def test_empty_context_no_call() -> None:
    op = FakeOpener(_sse(["무시됩니다 이 문장은."]))
    assert _llm(op).answer("q", []) == FALLBACK_ANSWER
    assert op.requests == []


def test_error_after_first_sentence_keeps_partial() -> None:
    body = _sse(["가나다라마바사 일. ", "가나다라"])[:-len("data: [DONE]\n\n")] + b"data: {broken\n\n"
    out = list(_llm(FakeOpener(body)).stream_sentences("q", CTX))
    assert out[0] == "가나다라마바사 일."
    assert CTX[0].answer not in " ".join(out)


def test_first_chunk_flushed_early_at_comma() -> None:
    deltas = ["주민등록등본은 가까운 주민센터에서, ", "신분증을 지참하시면 ", "발급받으실 수 있습니다. ",
              "수수료는 400원입니다."]
    consumed: list[int] = []

    def gen() -> Iterator[str]:
        for i, d in enumerate(deltas):
            consumed.append(i)
            yield d

    llm = _llm(FakeOpener(b""))
    llm._deltas = lambda q, top: gen()  # type: ignore[method-assign]
    it = llm.stream_sentences("q", CTX)
    first = next(it)
    assert first == "주민등록등본은 가까운 주민센터에서,"
    assert consumed == [0]  # 첫 델타 끝의 쉼표+공백에서 곧바로 나간다
    rest = list(it)
    assert rest == ["신분증을 지참하시면 발급받으실 수 있습니다.", "수수료는 400원입니다."]
    assert " ".join([first, *rest]) == "".join(deltas)


def test_early_chunk_needs_min_chars_and_only_first() -> None:
    op = FakeOpener(_sse(["네, 맞습니다. 민원실에서, 신분증을 내시고 받으시면 됩니다. ",
                          "추가로, 수수료를 내시면 되고, 기다리시면 됩니다."]))
    out = list(_llm(op).stream_sentences("q", CTX))
    assert out[0] == "네, 맞습니다. 민원실에서,"
    assert out[1:] == ["신분증을 내시고 받으시면 됩니다.", "추가로, 수수료를 내시면 되고, 기다리시면 됩니다."]


def test_early_chunk_not_counted_for_sentence_limit() -> None:
    op = FakeOpener(_sse(["가나다라마바사아자차카타파하거너, 일. ", "가나다라마바사 이. ", "가나다라마바사 삼. ",
                          "가나다라마바사 사. ", "가나다라마바사 오."]))
    out = list(_llm(op).stream_sentences("q", CTX))
    assert out == ["가나다라마바사아자차카타파하거너,", "일. 가나다라마바사 이.", "가나다라마바사 삼.", "가나다라마바사 사."]


def test_error_after_early_chunk_keeps_partial_no_faq_fallback() -> None:
    body = _sse(["가나다라마바사아자차카타파하거너, ", "타파하"])[:-len("data: [DONE]\n\n")] + b"data: {broken\n\n"
    out = list(_llm(FakeOpener(body)).stream_sentences("q", CTX))
    assert out[0] == "가나다라마바사아자차카타파하거너,"
    assert CTX[0].answer not in " ".join(out)
