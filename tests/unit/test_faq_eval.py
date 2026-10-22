import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "make_faq_eval.py"


@pytest.fixture(scope="module")
def mfe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_faq_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows() -> list[dict[str, Any]]:
    rows = [{"id": f"faq-{i:03d}", "question": f"합성 질문 {i}번 항목"} for i in range(1, 6)]
    topics = [
        "어린이 예방접종 일정",
        "자동차 등록 이전",
        "여권 재발급 신청",
        "쓰레기 대형폐기물 배출",
        "도서관 회원증 발급",
        "주차 과태료 납부",
        "전입 신고 방법",
        "건강검진 대상자 확인",
    ]
    for n, q in enumerate(topics, start=6):
        rows.append({"id": f"faq-{n:03d}", "question": q})
    return rows


def test_rules_fixed_outputs(mfe: ModuleType) -> None:
    assert mfe.p0_suffix_drop("주민등록등본은 어떻게") == "주민등록등본 어떻 알려주세요"
    assert mfe.p0_suffix_drop("여권 재발급") == "여권 재발 알려주세요"
    assert mfe.p1_swap("여권 재발급 신청") == "재발급 여권 신청 어떻게 해요?"
    assert mfe.p2_keywords("쓰레기 대형폐기물 배출") == "쓰레기 대형폐기물 궁금해요"
    assert mfe.p2_keywords("가나 다라 마바") == "가나 다라 궁금해요"
    assert mfe.p3_nospace("어린이 예방접종 일정") == "어린이예방접종일정?"


def test_build_eval_layout_and_rule_cycle(mfe: ModuleType) -> None:
    out = mfe.build_eval(_rows(), 8, 20261022)
    assert len(out) == 10
    assert [r["kind"] for r in out[:2]] == ["seed", "seed"]
    assert all(r["expected_id"] == "faq-001" for r in out[:2])
    assert [r["kind"] for r in out[2:]] == list(mfe.RULES) * 2
    assert all(list(r) == ["query", "expected_id", "kind"] for r in out)


def test_same_seed_same_output(mfe: ModuleType) -> None:
    a = mfe.build_eval(_rows(), 6, 7)
    b = mfe.build_eval(_rows(), 6, 7)
    assert a == b


def test_main_writes_identical_bytes(mfe: ModuleType, tmp_path: Path) -> None:
    import json

    faq = tmp_path / "faq.jsonl"
    faq.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _rows()), encoding="utf-8"
    )
    out1, out2 = tmp_path / "e1.jsonl", tmp_path / "e2.jsonl"
    assert mfe.main(["--faq", str(faq), "--out", str(out1), "--n", "4"]) == 0
    assert mfe.main(["--faq", str(faq), "--out", str(out2), "--n", "4"]) == 0
    assert out1.read_bytes() == out2.read_bytes()
    assert len(out1.read_text(encoding="utf-8").splitlines()) == 6


def test_candidates_conditions(mfe: ModuleType) -> None:
    rows = _rows() + [
        {"id": "faq-014", "question": "여권 재발급 신청서"},  # near-dup of faq-008
        {"id": "faq-015", "question": "단어하나뿐인질문"},  # 1 word
        {"id": "faq-016", "question": "가 나"},  # < 6 chars
    ]
    ids = [r["id"] for r in mfe.candidates(rows)]
    assert "faq-008" not in ids and "faq-014" not in ids
    assert "faq-015" not in ids and "faq-016" not in ids
    assert all(mfe.id_num(i) >= 6 for i in ids)
    assert ids == sorted(ids)
    assert "faq-006" in ids and "faq-013" in ids


def test_too_few_candidates_warns(mfe: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    out = mfe.build_eval(_rows(), 50, 1)
    assert len(out) == 2 + 8
    assert "warning" in capsys.readouterr().err
