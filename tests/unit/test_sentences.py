from app.pipeline.sentences import MAX_CHARS, MIN_CHARS, split_sentences


def _lossless(text: str, parts: list[str]) -> bool:
    return "".join(parts).replace(" ", "") == text.replace(" ", "").replace("\n", "")


def test_empty_and_blank() -> None:
    assert split_sentences("") == []
    assert split_sentences("   \n  ") == []


def test_three_korean_sentences() -> None:
    t = "경기도 시흥시 인구에 대해 안내해드릴게요. 시흥시의 인구는 하루하루 변화하고 있습니다. 자세한 통계를 확인하시려면 아래 링크를 클릭해주세요."
    parts = split_sentences(t)
    assert len(parts) == 3
    assert parts[0].endswith("요.")
    assert _lossless(t, parts)


def test_question_and_exclamation_boundaries() -> None:
    t = "신분증을 가져오셨나요? 꼭 지참하셔야 합니다! 감사합니다 안녕히 가세요。"
    assert split_sentences(t) == ["신분증을 가져오셨나요?", "꼭 지참하셔야 합니다!", "감사합니다 안녕히 가세요。"]


def test_decimal_and_url_not_boundary() -> None:
    t = "수수료는 1.5배로 인상되었습니다. 자세한 내용은 www.go.kr 에서 확인하세요."
    parts = split_sentences(t)
    assert parts == ["수수료는 1.5배로 인상되었습니다.", "자세한 내용은 www.go.kr 에서 확인하세요."]


def test_newline_is_boundary_and_whitespace_normalized() -> None:
    t = "첫 번째 줄의 안내 문장입니다\n두 번째   줄의 안내 문장입니다"
    assert split_sentences(t) == ["첫 번째 줄의 안내 문장입니다", "두 번째 줄의 안내 문장입니다"]


def test_short_piece_merged_into_next() -> None:
    t = "1. 신분증을 준비해 주시기 바랍니다. 2. 수수료를 납부해 주시기 바랍니다."
    parts = split_sentences(t)
    assert parts == ["1. 신분증을 준비해 주시기 바랍니다.", "2. 수수료를 납부해 주시기 바랍니다."]
    assert all(len(p) >= MIN_CHARS for p in parts)


def test_short_last_piece_merged_into_previous() -> None:
    t = "민원실은 평일 오전 9시부터 운영합니다. 감사합니다."
    assert split_sentences(t) == ["민원실은 평일 오전 9시부터 운영합니다. 감사합니다."]


def test_single_short_piece_kept() -> None:
    assert split_sentences("네.") == ["네."]


def test_long_piece_split_at_comma() -> None:
    clause = "가" * 60
    t = f"{clause}, {clause}, {clause}."
    parts = split_sentences(t)
    assert len(parts) >= 2
    assert all(len(p) <= MAX_CHARS for p in parts)
    assert parts[0].endswith(",")
    assert _lossless(t, parts)


def test_long_piece_split_at_space_when_no_comma() -> None:
    t = " ".join(["단어열"] * 80) + "."
    parts = split_sentences(t)
    assert len(parts) >= 2
    assert all(len(p) <= MAX_CHARS for p in parts)
    assert _lossless(t, parts)


def test_long_piece_without_spaces_not_split() -> None:
    t = "가" * 200
    assert split_sentences(t) == [t]


def test_order_preserved_and_lossless() -> None:
    t = "하나 둘 셋 넷 다섯입니다. 여섯 일곱 여덟입니다.\n아홉 열 열하나입니다! 끝입니다?"
    parts = split_sentences(t)
    assert _lossless(t, parts)
    assert parts[0].startswith("하나")
