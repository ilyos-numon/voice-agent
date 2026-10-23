"""data/presets/<id>/preset.json 을 읽어 프리셋 상담원을 만든다."""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.knowledge import parse_faq_csv
from app.agents.models import Agent, AgentSettings, Chunk, merge_settings
from app.pipeline.bm25 import load_faq_any

PRESET_FILE = "preset.json"
_KEYS = ("preset_id", "order", "title", "description", "name", "sample_questions", "settings", "source", "license")


@dataclass(frozen=True)
class Preset:
    preset_id: str
    title: str
    description: str
    sample_questions: tuple[str, str, str]
    agent: Agent


def _chunks(base: Path, source: Any) -> tuple[Chunk, ...]:
    if not isinstance(source, Mapping) or not isinstance(source.get("path"), str):
        raise ValueError(f"{base}: source.path가 없습니다")  # noqa: TRY004
    path = base / source["path"]
    kind = source.get("kind")
    if kind == "faq_jsonl":
        return tuple(
            Chunk(chunk_id=it.id, title=it.question, text=it.answer, index_text=it.question, origin="preset")
            for it in load_faq_any(path)
        )
    if kind == "faq_csv":
        text = path.read_text(encoding="utf-8")
        chunks, _ = parse_faq_csv(text, max_rows=max(1, text.count("\n") + 1), max_chars=len(text))
        return tuple(dataclasses.replace(c, origin="preset") for c in chunks)
    raise ValueError(f"{base}: 알 수 없는 source.kind입니다: {kind}")


def _load_one(base: Path, clock: Callable[[], float]) -> tuple[int, Preset]:
    raw = json.loads((base / PRESET_FILE).read_text(encoding="utf-8"))
    missing = [k for k in _KEYS if k not in raw]
    if missing:
        raise ValueError(f"{base}: 필드가 없습니다: {', '.join(missing)}")
    samples = raw["sample_questions"]
    if not isinstance(samples, list) or len(samples) != 3 or not all(isinstance(s, str) and s for s in samples):
        raise ValueError(f"{base}: sample_questions는 문자열 3개여야 합니다")
    if not isinstance(raw["order"], int) or not isinstance(raw["settings"], Mapping):
        raise ValueError(f"{base}: order 또는 settings 형식이 틀렸습니다")  # noqa: TRY004
    preset_id = str(raw["preset_id"])
    agent = Agent(
        agent_id=f"preset-{preset_id}",
        name=str(raw["name"]),
        preset_id=preset_id,
        settings=merge_settings(AgentSettings(), raw["settings"]),
        chunks=_chunks(base, raw["source"]),
        created_at=clock(),
        expires_at=None,
    )
    preset = Preset(
        preset_id=preset_id,
        title=str(raw["title"]),
        description=str(raw["description"]),
        sample_questions=(samples[0], samples[1], samples[2]),
        agent=agent,
    )
    return raw["order"], preset


def load_presets(presets_dir: Path, clock: Callable[[], float] = time.time) -> list[Preset]:
    loaded = [
        _load_one(d, clock) for d in sorted(presets_dir.iterdir()) if (d / PRESET_FILE).is_file()
    ]
    loaded.sort(key=lambda t: t[0])
    return [p for _, p in loaded]
