"""Run a preset agent's scorecard in-process (no server) and optionally check it against an older run.

Usage (from repo root):
  uv run --no-sync python scripts/scorecard.py --preset restaurant --n 10 --no-voice --out out.json
  uv run --no-sync python scripts/scorecard.py --preset restaurant --n 10 --no-voice \
      --out out2.json --check-against out.json

Settings come from env/.env (same build_stt/build_tts/build_agent_runtime as the server).
Writes <out> (ReportOut JSON) and <out>.md (table). Prints one SCORECARD line; with
--check-against also "REPRO OK" (exit 0) or "REPRO DIFF <summary>" (exit 1). Bad arguments exit 2.
Question and document text never go to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESETS = ("civil-kiosk", "restaurant", "hospital", "office-policy")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--preset", required=True, choices=PRESETS)
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--no-voice", action="store_true")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--check-against", type=Path, default=None)
    args = p.parse_args(argv)
    if args.n < 1:
        p.error("--n must be >= 1")
    if args.check_against is not None and not args.check_against.is_file():
        p.error(f"--check-against not found: {args.check_against}")
    if args.check_against is not None and args.check_against.resolve() == args.out.resolve():
        p.error("--out must differ from --check-against")
    return args


def _hits(part: dict[str, Any] | None) -> str:
    return "-" if part is None else f"{part['hits']}/{part['total']}"


def summary_line(preset: str, report: dict[str, Any]) -> str:
    fa = report["first_audio_ms"]
    return (f"SCORECARD preset={preset} text={_hits(report['text'])} voice={_hits(report['voice'])} "
            f"p50_ms={fa['p50']} p95_ms={fa['p95']}")


def _md_cell(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_markdown(preset: str, report: dict[str, Any]) -> str:
    lines = [
        f"# 성적표 — {preset}",
        "",
        f"> {report['caveat']}",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 질문 수 | {report['question_count']} |",
        f"| 글자 적중 | {_hits(report['text'])} |",
        f"| 음성 적중 | {_hits(report['voice'])} |",
        f"| 그대로 묻기 | {_hits(report['by_style']['verbatim'])} |",
        f"| 바꿔 묻기 | {_hits(report['by_style']['colloquial'])} |",
        f"| 첫 음성 p50 (ms, {report['first_audio_basis']}) | {report['first_audio_ms']['p50']} |",
        f"| 첫 음성 p95 (ms, {report['first_audio_basis']}) | {report['first_audio_ms']['p95']} |",
        "",
        "## 틀린 질문",
        "",
        "| qid | 채널 | 말투 | 질문 | 기대 | 받은 답 | 들은 말 | 이유 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in report["failures"]:
        got = f["got"]["chunk_id"] if f["got"] else "-"
        lines.append("| " + " | ".join(_md_cell(x) for x in (
            f["qid"], f["channel"], f["style"], f["question"], f["expected"]["chunk_id"], got,
            f["heard"] if f["heard"] is not None else "-", f["reason"])) + " |")
    lines += ["", "## 힌트", ""]
    lines += [f"- `{h['code']}` {h['message']} ({', '.join(h['chunk_ids'])})" for h in report["hints"]]
    return "\n".join(lines) + "\n"


def _repro_key(report: dict[str, Any]) -> tuple[str, str, list[str]]:
    return (_hits(report["text"]), _hits(report.get("voice")),
            [f"{f['qid']}:{f['channel']}" for f in report["failures"]])


def compare(old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """같으면 None, 다르면 요약 문자열."""
    o, n = _repro_key(old), _repro_key(new)
    if o == n:
        return None
    parts: list[str] = []
    if o[0] != n[0]:
        parts.append(f"text {o[0]}->{n[0]}")
    if o[1] != n[1]:
        parts.append(f"voice {o[1]}->{n[1]}")
    added = [k for k in n[2] if k not in o[2]]
    removed = [k for k in o[2] if k not in n[2]]
    if added:
        parts.append("new_failures=" + ",".join(added))
    if removed:
        parts.append("fixed=" + ",".join(removed))
    if not added and not removed and o[2] != n[2]:
        parts.append("failure_order_changed")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    old: dict[str, Any] | None = None
    if args.check_against is not None:
        try:
            old = json.loads(args.check_against.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: cannot read --check-against: {e}", file=sys.stderr)
            return 2

    from app.agents.questions import make_questions
    from app.agents.runtime import build_agent_runtime
    from app.agents.scorecard import run_scorecard
    from app.config import Settings
    from app.pipeline.runner import build_stt, build_tts

    settings = Settings()
    if not settings.presets_dir.is_absolute():
        settings = settings.model_copy(update={"presets_dir": ROOT / settings.presets_dir})
    rt = build_agent_runtime(settings, build_stt(settings), build_tts(settings))
    agent = rt.store.get(f"preset-{args.preset}")
    questions = make_questions(agent, args.n)
    report = run_scorecard(rt, agent, questions, voice=not args.no_voice)

    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(args.preset, report), encoding="utf-8")
    print(summary_line(args.preset, report))

    if old is not None:
        diff = compare(old, report)
        if diff is None:
            print("REPRO OK")
            return 0
        print(f"REPRO DIFF {diff}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
