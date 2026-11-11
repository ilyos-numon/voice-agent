import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL_SCRIPT = ROOT / "scripts" / "eval_colloquial.py"
BRIEF_SCRIPT = ROOT / "scripts" / "make_blind_brief.py"

SUMMARY_RE = re.compile(
    r"^n=\d+ n_answerable=\d+ n_none=\d+ top1=\d\.\d{3} top3=\d\.\d{3} none_correct=\d\.\d{3} "
    r"overall_top1=\d\.\d{3} leak_mean=\d\.\d{3} leak_p50=\d\.\d{3} top1_low_leak=\d\.\d{3} "
    r"n_low_leak=\d+ top1_high_leak=\d\.\d{3} n_high_leak=\d+$"
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ec() -> ModuleType:
    return _load("eval_colloquial", EVAL_SCRIPT)


@pytest.fixture(scope="module")
def mbb() -> ModuleType:
    return _load("make_blind_brief", BRIEF_SCRIPT)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def _faq_rows() -> list[dict[str, Any]]:
    topics = [
        ("어린이 예방접종 일정", "예방접종은 보건소에서 일정에 맞춰 받을 수 있습니다. " * 3),
        ("자동차 등록 이전", "자동차 이전등록은 차량등록사업소에서 신청합니다. " * 3),
        ("여권 재발급 신청", "짧은 답"),
        ("대형폐기물 배출 방법", "대형폐기물은 스티커를 구매해 부착한 뒤 배출합니다. " * 3),
        ("도서관 회원증 발급", "도서관 회원증은 신분증을 지참하고 방문하면 발급됩니다. " * 3),
    ]
    return [
        {
            "id": f"faq-{n:03d}",
            "question": q,
            "answer": a,
            "source": "합성",
            "category": "합성분류",
            "key": f"k{n}",
        }
        for n, (q, a) in enumerate(topics, start=6)
    ]


def test_leak_full_copy_is_one(ec: ModuleType) -> None:
    assert ec.leak("어린이 예방접종 일정", "어린이 예방접종 일정") == 1.0


def test_leak_no_shared_bigram_is_zero(ec: ModuleType) -> None:
    assert ec.leak("날씨 어때요", "어린이 예방접종 일정") == 0.0


def test_leak_space_removed_copy_is_one(ec: ModuleType) -> None:
    assert ec.leak("어린이예방접종일정", "어린이 예방접종 일정") == 1.0


def test_leak_empty_intent_is_zero(ec: ModuleType) -> None:
    assert ec.leak("아무 질문", "") == 0.0
    assert ec.leak("아무 질문", " ?! ") == 0.0


def test_bigrams_strip_punct_and_lower(ec: ModuleType) -> None:
    assert ec.bigrams("A b?") == {"ab"}
    assert ec.bigrams("") == set()


def _strict_rows(n_col: int = 26, n_none: int = 6) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(n_col):
        rows.append(
            {
                "qid": f"c{i + 1:02d}",
                "query": f"합성 질문 {i + 1}번",
                "expected_id": f"faq-{i + 6:03d}",
                "kind": "colloquial",
                "traits": ["spoken"],
            }
        )
    for i in range(n_none):
        rows.append(
            {
                "qid": f"n{i + 1:02d}",
                "query": f"범위 밖 질문 {i + 1}",
                "expected_id": None,
                "kind": "none",
                "traits": ["indirect"],
            }
        )
    return rows


def _ids() -> set[str]:
    return {f"faq-{i:03d}" for i in range(1, 60)}


def test_validate_rows_accepts_good_strict(ec: ModuleType) -> None:
    assert ec.validate_rows(_strict_rows(), _ids()) == []


def test_validate_rows_catches_errors(ec: ModuleType) -> None:
    rows = _strict_rows()
    rows[26]["expected_id"] = "faq-010"  # none + expected_id
    rows[0]["expected_id"] = "faq-999"  # unknown id
    rows[2]["qid"] = rows[1]["qid"]  # duplicate qid
    errs = ec.validate_rows(rows, _ids())
    assert all(re.match(r"^line=\d+ reason=.+", e) for e in errs)
    joined = "\n".join(errs)
    assert "line=27 " in joined
    assert "line=1 " in joined
    assert "line=3 " in joined


def test_validate_rows_legacy_only_checks_expected_id(ec: ModuleType) -> None:
    rows = [
        {"query": "x", "expected_id": "faq-001", "kind": "seed"},
        {"query": "y", "expected_id": "faq-999", "kind": "p0"},
    ]
    errs = ec.validate_rows(rows, {"faq-001"})
    assert len(errs) == 1 and errs[0].startswith("line=2 ")


def test_main_all_wrong_still_exit_zero(ec: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    faq = _write_jsonl(tmp_path / "faq.jsonl", _faq_rows())
    ev = _write_jsonl(
        tmp_path / "eval.jsonl",
        [
            {"query": "날씨 알려줘", "expected_id": "faq-006", "kind": "p0"},
            {"query": "버스 몇시", "expected_id": "faq-007", "kind": "p1"},
        ],
    )
    rc = ec.main(["--faq", str(faq), "--eval", str(ev)])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert SUMMARY_RE.match(out[0]), out[0]
    assert "top1=0.000" in out[0]
    assert out[-1] == "RESULT MEASURED"
    misses = [line for line in out if line.startswith("miss ")]
    assert len(misses) == 2
    assert "예방접종" not in "\n".join(out)


def test_main_schema_error_exit_two(ec: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    faq = _write_jsonl(tmp_path / "faq.jsonl", _faq_rows())
    bad = _strict_rows()
    bad[0]["traits"] = ["weird"]
    ev = _write_jsonl(tmp_path / "eval.jsonl", bad)
    for extra in ([], ["--validate"]):
        rc = ec.main(["--faq", str(faq), "--eval", str(ev), *extra])
        out = capsys.readouterr().out
        assert rc == 2
        assert "SCHEMA_ERROR line=" in out


def test_main_validate_ok(ec: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    faq_rows = [
        {"id": f"faq-{i:03d}", "question": f"질문 {i}", "answer": "답", "source": "합성"} for i in range(1, 40)
    ]
    faq = _write_jsonl(tmp_path / "faq.jsonl", faq_rows)
    ev = _write_jsonl(tmp_path / "eval.jsonl", _strict_rows())
    rc = ec.main(["--faq", str(faq), "--eval", str(ev), "--validate"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "SCHEMA OK n=32 n_answerable=26 n_none=6"


def test_brief_no_question_and_deterministic(
    mbb: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    faq = _write_jsonl(tmp_path / "faq.jsonl", _faq_rows())
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    assert mbb.main(["--faq", str(faq), "--out", str(a), "--n", "3"]) == 0
    assert mbb.main(["--faq", str(faq), "--out", str(b), "--n", "3"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == "faq=5 candidates=4 brief=3"
    assert a.read_bytes() == b.read_bytes()
    rows = [json.loads(line) for line in a.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert all(list(r) == ["target_id", "category", "answer"] for r in rows)
    assert '"question"' not in a.read_text(encoding="utf-8")
    nums = [int(r["target_id"].rsplit("-", 1)[1]) for r in rows]
    assert nums == sorted(nums)
    assert all(len(r["answer"]) <= 400 for r in rows)
