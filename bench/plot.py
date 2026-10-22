"""bench 결과 jsonl 두 개에서 단계별 지연 폭포 SVG 를 만든다 (외부 의존성 없음)."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from summarize import STAGE_ORDER, load_summary, stage_label

TITLE = "질문 1건 응답 시간 (중앙값, 공개 FAQ 50문항 × 3회)"
COLORS = {"stt_ms": "#4e79a7", "retrieve_ms": "#f28e2b", "llm_ms": "#59a14f", "tts_ms": "#e15759"}
OTHER_COLOR = "#9e9e9e"
SMALL_S = 0.15

__all__ = ["STAGE_ORDER", "render_svg"]


def _p50(s: dict, key: str) -> float:
    st = s["stages"].get(key)
    return float(st["p50"]) if st and st["p50"] is not None else 0.0


def _color(key: str) -> str:
    return COLORS.get(key, OTHER_COLOR)


def render_svg(before: dict, after: dict, width: int = 900) -> str:
    left, right, top = 80, 170, 60
    bar_h, gap = 36, 40
    b_total = float(before["total"]["p50"] or 0.0)
    a_fa = float(after["first_audio"]["p50"] or 0.0)
    a_total = float(after["total"]["p50"] or 0.0)
    max_s = max(b_total, a_total, 1.0) / 1000.0
    axis_s = math.ceil(max_s)
    plot_w = width - left - right
    scale = plot_w / axis_s  # px per second
    height = top + 2 * bar_h + gap + 70

    out: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="sans-serif">'
        ),
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="28" font-size="16" font-weight="bold">{escape(TITLE)}</text>',
    ]

    small_x: dict[float, float] = {}

    def seg(x: float, y: float, ms: float, label: str, color: str, dashed: bool = False) -> float:
        w = ms / 1000.0 * scale
        if dashed:
            out.append(
                f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="#ffffff" '
                f'stroke="{color}" stroke-width="1.5" stroke-dasharray="5,3"/>'
            )
        else:
            out.append(
                f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{color}" '
                'stroke="#ffffff" stroke-width="1"/>'
            )
        text = escape(f"{label} {ms / 1000.0:.1f}s")
        if ms / 1000.0 < SMALL_S:
            sx = max(x, small_x.get(y, 0.0))
            out.append(f'<text x="{sx:.1f}" y="{y - 4}" font-size="10" fill="#333333">{text}</text>')
            small_x[y] = sx + 7 * len(f"{label} {ms / 1000.0:.1f}s") + 8
        else:
            fill = "#333333" if dashed else "#ffffff"
            out.append(
                f'<text x="{x + w / 2:.1f}" y="{y + bar_h / 2 + 4}" font-size="12" '
                f'text-anchor="middle" fill="{fill}">{text}</text>'
            )
        return x + w

    # before
    y = top + 10
    out.append(f'<text x="{left - 10}" y="{y + bar_h / 2 + 5}" font-size="14" text-anchor="end">before</text>')
    x: float = left
    for k in before["stages"]:
        x = seg(x, y, _p50(before, k), stage_label(k), _color(k))
    out.append(f'<text x="{x + 8:.1f}" y="{y + bar_h / 2 + 5}" font-size="13">= {b_total / 1000:.1f}s</text>')

    # after
    y = top + 10 + bar_h + gap
    out.append(f'<text x="{left - 10}" y="{y + bar_h / 2 + 5}" font-size="14" text-anchor="end">after</text>')
    x = left
    head = [k for k in after["stages"] if k != "tts_ms"]
    head_ms = 0.0
    for k in head:
        v = _p50(after, k)
        head_ms += v
        x = seg(x, y, v, stage_label(k), _color(k))
    x = seg(x, y, max(a_fa - head_ms, 0.0), "TTS 첫 문장", _color("tts_ms"))
    x_end = seg(x, y, max(a_total - a_fa, 0.0), "나머지 스트리밍", _color("tts_ms"), dashed=True)
    first_end = left + a_fa / 1000.0 * scale
    out.append(
        f'<text x="{x_end + 8:.1f}" y="{y + bar_h / 2 + 5}" font-size="13">'
        f"= {escape('첫 음성까지')} {a_fa / 1000:.1f}s</text>"
    )
    out.append(
        f'<line x1="{first_end:.1f}" y1="{y - 6}" x2="{first_end:.1f}" y2="{y + bar_h + 6}" '
        'stroke="#333333" stroke-width="1.5"/>'
    )

    # axis
    ay = y + bar_h + 22
    out.append(f'<line x1="{left}" y1="{ay}" x2="{left + plot_w}" y2="{ay}" stroke="#333333"/>')
    for i in range(axis_s + 1):
        tx = left + i * scale
        out.append(f'<line x1="{tx:.1f}" y1="{ay}" x2="{tx:.1f}" y2="{ay + 5}" stroke="#333333"/>')
        out.append(f'<text x="{tx:.1f}" y="{ay + 18}" font-size="11" text-anchor="middle">{i}</text>')
    out.append(f'<text x="{left + plot_w + 12}" y="{ay + 18}" font-size="11">(s)</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", type=Path, default=Path("bench/results/before.jsonl"))
    ap.add_argument("--after", type=Path, default=Path("bench/results/after.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("bench/results/waterfall.svg"))
    ap.add_argument("--width", type=int, default=900)
    a = ap.parse_args(argv)
    for p in (a.before, a.after):
        if not p.exists():
            print(f"input not found: {p}", file=sys.stderr)
            return 1
    svg = render_svg(load_summary(a.before), load_summary(a.after), a.width)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(svg, encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
