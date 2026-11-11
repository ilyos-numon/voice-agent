import re

import pytest

from app.agents.knowledge import (
    CHUNK_MAX_CHARS,
    TITLE_MAX_CHARS,
    KnowledgeError,
    chunk_text,
    parse_faq_csv,
)
from app.agents.models import AgentSettings, merge_settings, settings_to_dict
from app.pipeline.sentences import split_sentences

ROWS = 300
CHARS = 100_000


def _codes(warnings: list) -> list[str]:
    return [w.code for w in warnings]


# ---- CSV ----


def test_csv_korean_header_skipped() -> None:
    chunks, warns = parse_faq_csv("질문,답변\n영업시간은?,9시부터 6시까지입니다.\n", ROWS, CHARS)
    assert len(chunks) == 1
    c = chunks[0]
    assert (c.chunk_id, c.title, c.text, c.index_text, c.origin) == (
        "q-001",
        "영업시간은?",
        "9시부터 6시까지입니다.",
        "영업시간은?\n9시부터 6시까지입니다.",
        "faq_csv",
    )
    assert warns == []


def test_csv_english_header_case_insensitive() -> None:
    chunks, _ = parse_faq_csv("Question,Answer\n주차 되나요?,네 됩니다.\n", ROWS, CHARS)
    assert [c.title for c in chunks] == ["주차 되나요?"]


def test_csv_without_header_keeps_first_row() -> None:
    chunks, _ = parse_faq_csv("영업시간은?,9시부터요.\n주차는?,가능합니다.\n", ROWS, CHARS)
    assert [c.chunk_id for c in chunks] == ["q-001", "q-002"]
    assert chunks[0].title == "영업시간은?"


def test_csv_bom_removed() -> None:
    chunks, _ = parse_faq_csv("﻿질문,답변\n휴무일은?,일요일입니다.\n", ROWS, CHARS)
    assert len(chunks) == 1
    assert chunks[0].title == "휴무일은?"


def test_csv_quoted_newline_allowed() -> None:
    chunks, _ = parse_faq_csv('질문,답변\n준비물은?,"신분증.\n도장."\n', ROWS, CHARS)
    assert len(chunks) == 1
    assert chunks[0].text == "신분증.\n도장."


def test_csv_empty_rows_warned_and_skipped() -> None:
    text = "질문,답변\n가격은?,만 원입니다.\n,\n\n질문만,\n위치는?,1층입니다.\n"
    chunks, warns = parse_faq_csv(text, ROWS, CHARS)
    assert [c.title for c in chunks] == ["가격은?", "위치는?"]
    assert [c.chunk_id for c in chunks] == ["q-001", "q-002"]
    assert _codes(warns).count("empty_row") == 3


def test_csv_duplicate_question_keeps_first() -> None:
    text = "질문,답변\n가격은?,만 원입니다.\n가격은?,이만 원입니다.\n"
    chunks, warns = parse_faq_csv(text, ROWS, CHARS)
    assert len(chunks) == 1
    assert chunks[0].text == "만 원입니다."
    assert _codes(warns) == ["duplicate_question"]


def test_csv_extra_columns_warned_once() -> None:
    text = "질문,답변,비고\n가격은?,만 원입니다.,메모\n위치는?,1층입니다.,메모2\n"
    chunks, warns = parse_faq_csv(text, ROWS, CHARS)
    assert [c.text for c in chunks] == ["만 원입니다.", "1층입니다."]
    assert _codes(warns) == ["extra_columns"]


def test_csv_too_many_rows() -> None:
    text = "".join(f"질문{i}?,답변{i}.\n" for i in range(4))
    with pytest.raises(KnowledgeError) as e:
        parse_faq_csv(text, 3, CHARS)
    assert e.value.code == "knowledge_too_large"


def test_csv_too_many_chars() -> None:
    with pytest.raises(KnowledgeError) as e:
        parse_faq_csv("가격은?,만 원입니다.\n", ROWS, 5)
    assert e.value.code == "knowledge_too_large"


def test_csv_bad_csv() -> None:
    with pytest.raises(KnowledgeError) as e:
        parse_faq_csv('질문,답변\n가격은?,"닫히지 않은 인용\n', ROWS, CHARS)
    assert e.value.code == "knowledge_bad_csv"


@pytest.mark.parametrize("text", ["", "질문,답변\n", "﻿\n\n", ",\n,\n"])
def test_csv_empty_input(text: str) -> None:
    with pytest.raises(KnowledgeError) as e:
        parse_faq_csv(text, ROWS, CHARS)
    assert e.value.code == "knowledge_empty"
    assert isinstance(e.value, ValueError)


# ---- 텍스트 ----


@pytest.mark.parametrize("text", ["", "   \n\n  \t "])
def test_text_empty_input(text: str) -> None:
    with pytest.raises(KnowledgeError) as e:
        chunk_text(text, 20_000)
    assert e.value.code == "knowledge_empty"


def test_text_too_large() -> None:
    with pytest.raises(KnowledgeError) as e:
        chunk_text("가" * 101, 100)
    assert e.value.code == "knowledge_too_large"


def test_text_headings_and_ids() -> None:
    text = (
        "# 영업 안내\n평일은 오전 9시부터 오후 6시까지 문을 엽니다. 점심시간은 12시부터 1시까지입니다.\n\n"
        "주차 안내\n건물 지하 주차장을 2시간 무료로 이용하실 수 있습니다.\n"
    )
    chunks, warns = chunk_text(text, 20_000)
    assert warns == []
    assert [c.chunk_id for c in chunks] == ["c-001", "c-002"]
    assert [c.title for c in chunks] == ["영업 안내", "주차 안내"]
    assert all(c.origin == "text" for c in chunks)
    assert chunks[0].index_text == chunks[0].title + "\n" + chunks[0].text
    assert all(re.fullmatch(r"c-\d{3}", c.chunk_id) for c in chunks)


def test_text_title_from_first_sentence_without_heading() -> None:
    first = "이 매장은 고객 여러분의 편의를 위해 연중무휴로 운영되며 공휴일에도 정상 영업을 합니다."
    chunks, _ = chunk_text(first + " 문의는 전화로 받습니다.", 20_000)
    assert len(chunks) == 1
    assert chunks[0].title == first[:TITLE_MAX_CHARS]
    assert len(chunks[0].title) <= TITLE_MAX_CHARS


def test_text_small_paragraphs_packed_under_same_heading() -> None:
    paras = [f"{i}번째 안내 문단입니다. 자세한 내용은 창구에 문의해 주시기 바랍니다." for i in range(3)]
    chunks, _ = chunk_text("# 안내\n" + "\n\n".join(paras), 20_000)
    assert len(chunks) == 1
    assert all(p in chunks[0].text for p in paras)


def _long_paragraph(n: int) -> str:
    return " ".join(f"{i}번 항목은 신청서와 신분증을 지참하여 민원 창구에서 접수하시면 됩니다." for i in range(n))


def test_text_paragraph_chunk_max_and_sentences_preserved() -> None:
    para = _long_paragraph(40)  # 약 1800자짜리 한 문단
    assert len(para) > CHUNK_MAX_CHARS
    text = "# 접수 안내\n" + para + "\n\n짧은 마지막 문단입니다. 감사합니다."
    chunks, _ = chunk_text(text, 20_000)
    assert len(chunks) >= 3
    assert all(len(c.text) <= CHUNK_MAX_CHARS for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    for sent in split_sentences(para):
        assert sent in joined
    assert "짧은 마지막 문단입니다." in joined


def test_text_single_huge_sentence_cut_at_max() -> None:
    sent = "가나다라마바사아자차" * 130  # 1300자, 종결부호 없음
    chunks, _ = chunk_text(sent, 20_000)
    assert all(len(c.text) <= CHUNK_MAX_CHARS for c in chunks)
    assert "".join(c.text for c in chunks).replace(" ", "") == sent


def test_text_heading_without_body_kept() -> None:
    chunks, _ = chunk_text("# 공지\n\n# 영업시간\n아침 9시에 엽니다.", 20_000)
    texts = [c.text for c in chunks]
    assert "공지" in texts
    assert any("아침 9시에 엽니다." in t for t in texts)


# ---- 설정 ----


def test_merge_settings_valid_patch() -> None:
    s = merge_settings(
        AgentSettings(),
        {"tone": "concise", "avoid_topics": ["가격", "정치"], "summary": True, "persona_name": "민원봇"},
    )
    assert s.tone == "concise"
    assert s.avoid_topics == ("가격", "정치")
    assert s.summary is True
    assert s.persona_name == "민원봇"
    d = settings_to_dict(s)
    assert d["avoid_topics"] == ["가격", "정치"]
    assert d["voice"] == "calm_female"


@pytest.mark.parametrize(
    "patch",
    [
        {"unknown_key": 1},
        {"tone": "angry"},
        {"voice": "robot"},
        {"answer_length": "long"},
        {"when_unknown": "ignore"},
        {"persona_name": ""},
        {"persona_name": "가" * 21},
        {"handoff_message": "가" * 101},
        {"avoid_topics": ["가"] * 11},
        {"avoid_topics": ["가" * 21]},
        {"avoid_topics": "가격"},
        {"summary": "yes"},
    ],
)
def test_merge_settings_invalid_raises(patch: dict) -> None:
    with pytest.raises(ValueError):
        merge_settings(AgentSettings(), patch)
