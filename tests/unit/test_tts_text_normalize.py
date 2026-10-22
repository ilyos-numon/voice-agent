from app.pipeline.tts_supertonic import sanitize_tts_text


def _ko_only(ch: str) -> bool:
    return ch not in "▶•※■"


def test_unsupported_chars_replaced_with_space() -> None:
    assert sanitize_tts_text("▶신청 방법:•방문", _ko_only) == "신청 방법: 방문"


def test_supported_text_unchanged() -> None:
    assert sanitize_tts_text("안녕하세요. 반갑습니다", _ko_only) == "안녕하세요. 반갑습니다"


def test_only_unsupported_becomes_empty() -> None:
    assert sanitize_tts_text("▶ ※ ■", _ko_only) == ""


def test_validator_called_once_per_distinct_char() -> None:
    calls: list[str] = []

    def v(ch: str) -> bool:
        calls.append(ch)
        return True

    sanitize_tts_text("aaab", v)
    assert sorted(calls) == ["a", "b"]
