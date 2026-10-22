import importlib.util
import json
from pathlib import Path
from types import ModuleType

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_faq.py"
SEED = ROOT / "data" / "faq" / "sample_faq.json"
RAW_NAME = "siheung_chatbot_faq_20250901.xlsx"
HEADERS = ["번호", "검토부서", "담당 팀", "대분류", "인텐트명", "답변", "연락처", "링크"]


@pytest.fixture(scope="module")
def pf() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_faq", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(n: int, cat: str, q: str, a: str) -> list[object]:
    return [n, "가부서", "가팀", cat, q, a, "", ""]


def _write_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(["시트 제목"])  # single string cell: not a header row
        ws.append(HEADERS)
        for r in rows:
            ws.append(r)
    wb.save(path)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run(pf: ModuleType, tmp_path: Path, *extra: str) -> tuple[int, list[dict[str, object]]]:
    out = tmp_path / "faq.jsonl"
    code = pf.main(
        [
            "--skip-download",
            "--raw-dir",
            str(tmp_path),
            "--seed",
            str(SEED),
            "--out",
            str(out),
            "--exclude",
            str(tmp_path / "exclude_keys.txt"),
            "--min-rows",
            "1",
            *extra,
        ]
    )
    return code, (_read_jsonl(out) if out.exists() else [])


def test_clean_text_removes_phone_url_email_html(pf: ModuleType) -> None:
    counts: dict[str, int] = {}
    s = "<b>문의</b> 031-123-4567 &amp; https://example.go.kr/x 또는 a@example.com 으로 연락"
    assert pf.clean_text(s, counts) == "문의 & 또는 으로 연락"
    assert counts == {"emails": 1, "urls": 1, "phones": 1}
    assert pf.clean_text("☎ 031-123-4567") == ""


def test_resolve_columns_keywords(pf: ModuleType) -> None:
    roles = pf.resolve_columns(["번호", "분야", "질문", "유사질문", "답변", "담당자", "전화번호"])
    assert roles == {"question": 2, "answer": 4, "category": 1, "drop": [5, 6]}


def test_resolve_columns_explicit_overrides_keywords(pf: ModuleType) -> None:
    headers = ["질문", "인텐트명", "답변", "검토부서", "대분류"]
    roles = pf.resolve_columns(headers, question_col="인텐트명", category_col="대분류")
    assert (roles["question"], roles["answer"], roles["category"]) == (1, 2, 4)
    with pytest.raises(pf.ColumnError):
        pf.resolve_columns(headers, question_col="없는열", strict=True)


def test_question_col_cli_overrides_source_default(pf: ModuleType, tmp_path: Path) -> None:
    _write_xlsx(tmp_path / RAW_NAME, {"전체": [_row(1, "복지", "노인 일자리", "노인 일자리 안내 답변입니다")]})
    code, rows = _run(pf, tmp_path, "--question-col", "대분류")
    assert code == 0
    assert rows[5]["question"] == "복지"


def test_missing_columns_exit_2(pf: ModuleType, tmp_path: Path) -> None:
    _write_xlsx(tmp_path / RAW_NAME, {"전체": [_row(1, "복지", "노인 일자리", "답변 내용입니다")]})
    code, rows = _run(pf, tmp_path, "--question-col", "없는열")
    assert code == 2
    assert rows == []


def test_xlsx_two_sheets_merge_ids_seed_first(pf: ModuleType, tmp_path: Path) -> None:
    ip = ".".join(["10"] * 4)
    full = [
        _row(1, "복지", "노인 일자리", "노인 일자리 사업은 복지과에서 안내합니다."),
        _row(2, "교통", "버스 노선 변경", "버스 노선 변경은 교통과 누리집에서 확인합니다."),
        _row(3, "행정", "서버 주소", f"접속 주소는 {ip} 입니다 확인하세요."),
        _row(4, "행정", "가", "한 글자 질문은 버립니다."),
        _row(5, "행정", "", "질문이 비어 있습니다."),
    ]
    part = [
        _row(1, "복지", "노인 일자리", "노인 일자리 사업은 복지과에서 안내합니다."),
        _row(6, "환경", "대형 폐기물 배출", "대형 폐기물은 신고 후 스티커를 붙여 배출합니다."),
    ]
    _write_xlsx(tmp_path / RAW_NAME, {"전체": full, "분야": part})
    stats_path = tmp_path / "stats.json"
    code, rows = _run(pf, tmp_path, "--stats-json", str(stats_path))
    assert code == 0
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert [r["id"] for r in rows[:5]] == [s["id"] for s in seed]
    assert all(r["category"] == "합성" for r in rows[:5])
    assert [r["id"] for r in rows[5:]] == ["faq-006", "faq-007", "faq-008"]
    assert [r["category"] for r in rows[5:]] == ["복지", "교통", "환경"]
    assert list(rows[5]) == ["id", "question", "answer", "source", "category", "key"]
    assert rows[5]["key"] == pf.make_key("siheung-faq", "노인 일자리")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert stats["raw_rows"] == 7
    assert stats["sheets"] == 2
    assert stats["dropped"] == {
        "empty": 1,
        "short": 1,
        "pattern": 1,
        "exact_dup": 1,
        "near_dup": 0,
        "excluded": 0,
    }
    assert "노인" not in stats_path.read_text(encoding="utf-8")


def test_near_duplicate_dropped(pf: ModuleType, tmp_path: Path) -> None:
    rows_in = [
        _row(1, "보건", "어린이 예방접종 일정", "예방접종 일정은 보건소에 문의합니다."),
        _row(2, "보건", "어린이 예방접종 일정표", "일정표는 보건소 누리집에 있습니다."),
        # near-duplicate of synthetic faq-001 question
        _row(3, "행정", "주민등록등본 발급에 필요한 것은", "신분증을 가져오세요 감사합니다."),
    ]
    _write_xlsx(tmp_path / RAW_NAME, {"전체": rows_in})
    stats_path = tmp_path / "stats.json"
    code, rows = _run(pf, tmp_path, "--stats-json", str(stats_path))
    assert code == 0
    assert [r["question"] for r in rows[5:]] == ["어린이 예방접종 일정"]
    assert json.loads(stats_path.read_text(encoding="utf-8"))["dropped"]["near_dup"] == 2


def test_exclude_keys_dropped(pf: ModuleType, tmp_path: Path) -> None:
    _write_xlsx(
        tmp_path / RAW_NAME,
        {
            "전체": [
                _row(1, "복지", "노인 일자리", "노인 일자리 안내 답변입니다."),
                _row(2, "교통", "버스 노선 변경", "버스 노선 안내 답변입니다."),
            ]
        },
    )
    key = pf.make_key("siheung-faq", "노인 일자리")
    (tmp_path / "exclude_keys.txt").write_text(f"# comment\n\n{key}\n", encoding="utf-8")
    stats_path = tmp_path / "stats.json"
    code, rows = _run(pf, tmp_path, "--stats-json", str(stats_path))
    assert code == 0
    assert [r["question"] for r in rows[5:]] == ["버스 노선 변경"]
    assert rows[5]["id"] == "faq-006"
    assert json.loads(stats_path.read_text(encoding="utf-8"))["dropped"]["excluded"] == 1


def test_min_rows_exit_4_and_no_output(pf: ModuleType, tmp_path: Path) -> None:
    _write_xlsx(tmp_path / RAW_NAME, {"전체": [_row(1, "복지", "노인 일자리", "답변 내용입니다.")]})
    code, rows = _run(pf, tmp_path, "--min-rows", "100")
    assert code == 4
    assert rows == []


def test_missing_raw_file_exit_3(pf: ModuleType, tmp_path: Path) -> None:
    code, _ = _run(pf, tmp_path)
    assert code == 3


def test_csv_and_json_readers(pf: ModuleType, tmp_path: Path) -> None:
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("질문,답변\n노인 일자리,안내 답변입니다\n", encoding="utf-8-sig")
    json_path = tmp_path / "a.json"
    json_path.write_text(
        json.dumps([{"question": "버스 노선", "answer": "안내 답변"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (_, h1, r1), = pf.read_tables(csv_path, "csv")
    (_, h2, r2), = pf.read_tables(json_path, "json")
    assert (h1, r1) == (["질문", "답변"], [["노인 일자리", "안내 답변입니다"]])
    assert (h2, r2) == (["question", "answer"], [["버스 노선", "안내 답변"]])
