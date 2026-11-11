import csv
import json
from pathlib import Path

import pytest

from app.agents.models import AgentSettings
from app.agents.presets import Preset, load_presets

ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = ROOT / "data" / "presets"
CSV_PRESETS = ("restaurant", "hospital", "office-policy")

# 합성 FAQ에 들어가면 안 되는 고유명사 (지역·업체 형태·사람 호칭)
FORBIDDEN = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충청",
    "전라", "경상", "제주", "시흥", "강남", "판교",
    "주식회사", "(주)", "㈜", "유한회사", "삼성", "현대", "엘지", "LG", "SK", "롯데",
    "씨", "님께서", "선생님", "원장님", "대표님", "과장님", "부장님",
)


@pytest.fixture(scope="module")
def presets() -> list[Preset]:
    return load_presets(PRESETS_DIR, clock=lambda: 1000.0)


def _bigrams(s: str) -> set[str]:
    t = "".join(s.split())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _overlap(sample: str, question: str) -> float:
    a = _bigrams(sample)
    return len(a & _bigrams(question)) / len(a) if a else 0.0


def _csv_rows(preset_id: str) -> list[list[str]]:
    with open(PRESETS_DIR / preset_id / "faq.csv", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))[1:]


def test_four_presets_in_order(presets: list[Preset]) -> None:
    assert [p.preset_id for p in presets] == ["civil-kiosk", "restaurant", "hospital", "office-policy"]
    assert [p.title for p in presets] == ["민원 키오스크", "식당 주문 안내", "병원 접수 안내", "사내 규정 Q&A"]


def test_persona_names(presets: list[Preset]) -> None:
    names = [p.agent.settings.persona_name for p in presets]
    assert names == ["민원 도우미", "주문 도우미", "접수 도우미", "규정 도우미"]


def test_agent_fields(presets: list[Preset]) -> None:
    for p in presets:
        a = p.agent
        assert a.agent_id == f"preset-{p.preset_id}"
        assert a.preset_id == p.preset_id
        assert a.expires_at is None
        assert a.created_at == 1000.0
        assert 1 <= len(a.name) <= 30
        assert isinstance(a.settings, AgentSettings)
        assert p.description
        assert all(c.origin == "preset" for c in a.chunks)


def test_civil_kiosk_575_original_ids(presets: list[Preset]) -> None:
    civil = presets[0].agent
    assert len(civil.chunks) == 575
    rows = [json.loads(line) for line in (ROOT / "data/faq/faq.jsonl").read_text("utf-8").splitlines() if line.strip()]
    first = civil.chunks[0]
    assert first.chunk_id == rows[0]["id"] == "faq-001"
    assert first.title == rows[0]["question"]
    assert first.text == rows[0]["answer"]
    assert first.index_text == first.title
    assert [c.chunk_id for c in civil.chunks] == [r["id"] for r in rows]


@pytest.mark.parametrize("preset_id", CSV_PRESETS)
def test_csv_presets_row_count_and_ids(presets: list[Preset], preset_id: str) -> None:
    p = next(x for x in presets if x.preset_id == preset_id)
    assert 20 <= len(p.agent.chunks) <= 30
    assert len(p.agent.chunks) == len(_csv_rows(preset_id))
    assert [c.chunk_id for c in p.agent.chunks] == [f"q-{i:03d}" for i in range(1, len(p.agent.chunks) + 1)]
    for c in p.agent.chunks:
        assert c.index_text == f"{c.title}\n{c.text}"


@pytest.mark.parametrize("preset_id", CSV_PRESETS)
def test_csv_answers_shape(preset_id: str) -> None:
    rows = _csv_rows(preset_id)
    assert len(rows) == 24
    assert all(len(r) == 2 for r in rows)
    assert all(40 <= len(r[1]) <= 200 for r in rows)
    multi = [r for r in rows if 2 <= sum(r[1].count(m) for m in (".", "?", "!")) <= 4]
    assert multi


def test_sample_questions_overlap_rows(presets: list[Preset]) -> None:
    for p in presets:
        assert len(p.sample_questions) == 3
        titles = [c.title for c in p.agent.chunks]
        for s in p.sample_questions:
            best = max(_overlap(s, t) for t in titles)
            assert best >= 0.3, (p.preset_id, s, best)


@pytest.mark.parametrize("preset_id", CSV_PRESETS)
def test_no_forbidden_proper_nouns(preset_id: str) -> None:
    text = (PRESETS_DIR / preset_id / "faq.csv").read_text("utf-8")
    text += (PRESETS_DIR / preset_id / "preset.json").read_text("utf-8")
    hits = [w for w in FORBIDDEN if w in text]
    assert hits == []


def test_preset_json_schema() -> None:
    for d in sorted(PRESETS_DIR.iterdir()):
        raw = json.loads((d / "preset.json").read_text("utf-8"))
        assert set(raw) == {
            "preset_id", "order", "title", "description", "name",
            "sample_questions", "settings", "source", "license",
        }
        assert raw["preset_id"] == d.name
        assert raw["source"]["kind"] in ("faq_jsonl", "faq_csv")
        assert (d / raw["source"]["path"]).is_file()


def _write_preset(base: Path, pid: str, order: int, **over: object) -> None:
    d = base / pid
    d.mkdir()
    (d / "faq.csv").write_text("질문,답변\n영업시간은?,9시부터 6시까지입니다.\n", "utf-8")
    raw: dict[str, object] = {
        "preset_id": pid, "order": order, "title": pid, "description": "설명", "name": "이름",
        "sample_questions": ["영업시간", "영업", "시간"], "settings": {},
        "source": {"kind": "faq_csv", "path": "faq.csv"}, "license": "CC0-1.0",
    }
    raw.update(over)
    (d / "preset.json").write_text(json.dumps(raw, ensure_ascii=False), "utf-8")


def test_order_field_sorts_not_dirname(tmp_path: Path) -> None:
    _write_preset(tmp_path, "a", 2)
    _write_preset(tmp_path, "b", 1)
    assert [p.preset_id for p in load_presets(tmp_path)] == ["b", "a"]


def test_settings_partial_merged_on_defaults(tmp_path: Path) -> None:
    _write_preset(tmp_path, "a", 1, settings={"tone": "concise"})
    s = load_presets(tmp_path)[0].agent.settings
    assert s.tone == "concise"
    assert s.persona_name == AgentSettings().persona_name


@pytest.mark.parametrize(
    "over",
    [
        {"settings": {"tone": "angry"}},
        {"sample_questions": ["하나", "둘"]},
        {"source": {"kind": "pdf", "path": "faq.csv"}},
    ],
)
def test_bad_preset_raises(tmp_path: Path, over: dict[str, object]) -> None:
    _write_preset(tmp_path, "a", 1, **over)
    with pytest.raises(ValueError):
        load_presets(tmp_path)
