"""Download a public Korean civil-service FAQ, normalize it to JSONL and check the BM25 index.

Usage (from repo root):
  uv run python scripts/prepare_faq.py                       # download + normalize
  uv run python scripts/prepare_faq.py --skip-download       # reuse data/raw/<file>

Exit codes: 0 ok, 2 column detection failed, 3 download failed,
4 result below --min-rows or larger than 2 MB.
Only statistics are printed; FAQ text never goes to stdout.
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_BYTES = 2 * 1024 * 1024
MIN_DOWNLOAD_BYTES = 100 * 1024
NEAR_DUP_JACCARD = 0.6
SEED_CATEGORY = "합성"


@dataclass(frozen=True)
class Source:
    name: str
    portal_id: str
    detail_url: str
    file_url: str
    resolve: tuple[str, str]  # (publicDataPk, publicDataDetailPk)
    filename: str
    fmt: str  # "xlsx" | "json" | "csv"
    license: str
    source_label: str
    question_col: str | None = None
    answer_col: str | None = None
    category_col: str | None = None


SOURCES: dict[str, Source] = {
    "siheung-faq": Source(
        name="경기도 시흥시 챗봇 FAQ 시나리오",
        portal_id="15148282",
        detail_url="https://www.data.go.kr/data/15148282/fileData.do",
        file_url=(
            "https://www.data.go.kr/cmm/cmm/fileDownload.do"
            "?atchFileId=FILE_000000003509582&fileDetailSn=1"
        ),
        resolve=("15148282", "uddi:f488be8a-2984-4b10-b2db-ea9782fd4892"),
        filename="siheung_chatbot_faq_20250901.xlsx",
        fmt="xlsx",
        license="이용허락범위 제한 없음 (공공데이터포털)",
        source_label="경기도 시흥시 챗봇 FAQ 시나리오 (공공데이터포털 15148282, 2025-09-01)",
        question_col="인텐트명",
        answer_col="답변",
        category_col="대분류",
    ),
}

RESOLVE_URL = "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"

QUESTION_KW = ["질문", "질의", "문의", "제목", "question"]
QUESTION_NOT_KW = ["유사", "답변", "답"]
ANSWER_KW = ["답변", "응답", "answer", "내용"]
CATEGORY_KW = ["분야", "분류", "카테고리", "유형", "부서", "category"]
DROP_KW = ["담당", "성명", "작성자", "이름", "전화", "연락처", "url", "링크"]

_TAG_RE = re.compile(r"<[^>]+>")
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_URL_RE = re.compile(
    r"https?://\S+|www\.\S+|\b[\w.-]+\.(go\.kr|or\.kr|co\.kr|kr|com|net|org)(/\S*)?"
)
_PHONE_RE = re.compile(r"(\(?0\d{1,2}\)?[-.\s]?)?\d{3,4}[-.\s]\d{4}")
_PHONE_MARK_RE = re.compile(r"☎|TEL|Tel|tel\.?")
_SPACE_RE = re.compile(r"\s+")
_IPV4_RE = re.compile(r"([0-9]{1,3}\.){3}[0-9]{1,3}")

DROP_REASONS = ("empty", "short", "pattern", "exact_dup", "near_dup", "excluded")


class DownloadError(Exception):
    pass


class ColumnError(Exception):
    def __init__(self, headers: list[str], message: str) -> None:
        super().__init__(message)
        self.headers = headers


# ---------------------------------------------------------------- text


def clean_text(s: str, counts: dict[str, int] | None = None) -> str:
    s = html.unescape(s)
    s = _TAG_RE.sub(" ", s)
    s, n_email = _EMAIL_RE.subn(" ", s)
    s, n_url = _URL_RE.subn(" ", s)
    s, n_phone = _PHONE_RE.subn(" ", s)
    s = _PHONE_MARK_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    if counts is not None:
        counts["emails"] = counts.get("emails", 0) + n_email
        counts["urls"] = counts.get("urls", 0) + n_url
        counts["phones"] = counts.get("phones", 0) + n_phone
    return unicodedata.normalize("NFC", s)


def make_key(source_id: str, raw_question: str) -> str:
    return hashlib.sha1(f"{source_id}|{raw_question}".encode()).hexdigest()[:12]


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


def _norm_header(h: str) -> str:
    return unicodedata.normalize("NFC", h).strip().lower()


# ---------------------------------------------------------------- columns


def resolve_columns(
    headers: list[str],
    question_col: str | None = None,
    answer_col: str | None = None,
    category_col: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Map header list to roles: question/answer/category index (or None) and drop indices.

    Explicit names match exactly (after strip). With strict=False a missing explicit name
    falls back to keyword rules; with strict=True it is an error.
    """
    norm = [_norm_header(_cell_str(h)) for h in headers]

    def explicit(name: str | None) -> int | None:
        if name is None:
            return None
        target = _norm_header(name)
        for i, h in enumerate(norm):
            if h == target:
                return i
        if strict:
            raise ColumnError([_cell_str(h) for h in headers], f"column not found: {name}")
        return None

    q = explicit(question_col)
    if q is None:
        q = next(
            (
                i
                for i, h in enumerate(norm)
                if any(k in h for k in QUESTION_KW) and not any(k in h for k in QUESTION_NOT_KW)
            ),
            None,
        )
    a = explicit(answer_col)
    if a is None:
        a = next(
            (i for i, h in enumerate(norm) if i != q and any(k in h for k in ANSWER_KW)), None
        )
    c = explicit(category_col)
    if c is None:
        c = next((i for i, h in enumerate(norm) if any(k in h for k in CATEGORY_KW)), None)
    if q is None or a is None:
        raise ColumnError(
            [_cell_str(h) for h in headers], "question/answer column not identified"
        )
    drop = [i for i, h in enumerate(norm) if any(k in h for k in DROP_KW) and i not in (q, a)]
    return {"question": q, "answer": a, "category": c, "drop": drop}


# ---------------------------------------------------------------- readers


Table = tuple[str, list[str], list[list[Any]]]  # (sheet name, headers, rows)


def _iter_xlsx(path: Path) -> Iterator[Table]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            headers: list[str] | None = None
            rows: list[list[Any]] = []
            for row in ws.iter_rows(values_only=True):
                cells = list(row)
                if headers is None:
                    if sum(1 for v in cells if isinstance(v, str) and v.strip()) >= 2:
                        headers = [_cell_str(v) for v in cells]
                    continue
                rows.append(cells)
            if headers is not None:
                yield ws.title, headers, rows
    finally:
        wb.close()


def _iter_json(path: Path) -> Iterator[Table]:
    data = json.loads(path.read_text(encoding="utf-8"))
    headers: list[str] = []
    for d in data:
        for k in d:
            if k not in headers:
                headers.append(k)
    yield path.stem, headers, [[d.get(h) for h in headers] for d in data]


def _iter_csv(path: Path) -> Iterator[Table]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = [[d.get(h) for h in headers] for d in reader]
    yield path.stem, headers, rows


def read_tables(path: Path, fmt: str) -> list[Table]:
    readers = {"xlsx": _iter_xlsx, "json": _iter_json, "csv": _iter_csv}
    if fmt not in readers:
        raise ValueError(f"unknown fmt: {fmt}")
    return list(readers[fmt](path))


# ---------------------------------------------------------------- download


def _is_valid_payload(data: bytes, fmt: str) -> bool:
    if len(data) < MIN_DOWNLOAD_BYTES:
        return False
    if fmt == "xlsx":
        return data[:4] == b"PK\x03\x04"
    return not data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html"))


def _http(req: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def download(source: Source, dest: Path) -> int:
    status, data = _http(urllib.request.Request(source.file_url))
    url = source.file_url
    if not _is_valid_payload(data, source.fmt):
        body = urllib.parse.urlencode(
            {
                "publicDataPk": source.resolve[0],
                "publicDataDetailPk": source.resolve[1],
                "atchFileId": "",
                "fileDetailSn": "1",
                "publicDataTyCode": "PR0051",
            }
        ).encode()
        req = urllib.request.Request(
            RESOLVE_URL,
            data=body,
            method="POST",
            headers={"Referer": source.detail_url, "X-Requested-With": "XMLHttpRequest"},
        )
        r_status, r_data = _http(req)
        url = RESOLVE_URL
        status, data = r_status, b""
        try:
            info = json.loads(r_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            info = {}
        if isinstance(info, dict) and info.get("status") and info.get("atchFileId"):
            query = urllib.parse.urlencode(
                {"atchFileId": info["atchFileId"], "fileDetailSn": info.get("fileDetailSn", "1")}
            )
            url = f"{DOWNLOAD_URL}?{query}"
            status, data = _http(urllib.request.Request(url))
        if not _is_valid_payload(data, source.fmt):
            raise DownloadError(f"download failed: {url} status={status} bytes={len(data)}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


# ---------------------------------------------------------------- normalize


def load_exclude_keys(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.add(line)
    return keys


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def normalize(
    tables: list[Table],
    seed: list[dict[str, Any]],
    source_id: str,
    source_label: str,
    exclude_keys: set[str],
    question_col: str | None = None,
    answer_col: str | None = None,
    category_col: str | None = None,
    strict_cols: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.pipeline.bm25 import tokenize

    dropped = dict.fromkeys(DROP_REASONS, 0)
    cleaned: dict[str, int] = {"phones": 0, "urls": 0, "emails": 0}
    out: list[dict[str, Any]] = []
    seen_q: set[str] = set()
    seen_bigrams: list[set[str]] = []
    postings: dict[str, list[int]] = {}

    def remember(question: str) -> None:
        seen_q.add(question)
        bg = set(tokenize(question))
        idx = len(seen_bigrams)
        seen_bigrams.append(bg)
        for t in bg:
            postings.setdefault(t, []).append(idx)

    def is_near_dup(question: str) -> bool:
        bg = set(tokenize(question))
        candidates = {i for t in bg for i in postings.get(t, [])}
        return any(_jaccard(bg, seen_bigrams[i]) >= NEAR_DUP_JACCARD for i in candidates)

    for row in seed:
        out.append(
            {
                "id": row["id"],
                "question": row["question"],
                "answer": row["answer"],
                "source": row["source"],
                "category": SEED_CATEGORY,
                "key": make_key("seed", row["question"]),
            }
        )
        remember(clean_text(row["question"]))

    raw_rows = 0
    public: list[tuple[str, str, str, str]] = []
    for sheet, headers, rows in tables:
        roles = resolve_columns(headers, question_col, answer_col, category_col, strict_cols)
        qi, ai, ci = roles["question"], roles["answer"], roles["category"]
        for cells in rows:
            if all(_cell_str(v).strip() == "" for v in cells):
                continue
            raw_rows += 1
            raw_q = _cell_str(cells[qi]) if qi < len(cells) else ""
            raw_a = _cell_str(cells[ai]) if ai < len(cells) else ""
            q = clean_text(raw_q, cleaned)
            a = clean_text(raw_a, cleaned)
            if not q or not a:
                dropped["empty"] += 1
                continue
            if len(q) < 2 or len(a) < 5:
                dropped["short"] += 1
                continue
            if _IPV4_RE.search(raw_q) or _IPV4_RE.search(raw_a):
                dropped["pattern"] += 1
                continue
            if q in seen_q:
                dropped["exact_dup"] += 1
                continue
            if is_near_dup(q):
                dropped["near_dup"] += 1
                continue
            key = make_key(source_id, raw_q)
            if key in exclude_keys:
                dropped["excluded"] += 1
                continue
            remember(q)
            cat = ""
            if ci is not None and ci < len(cells):
                cat = unicodedata.normalize("NFC", _cell_str(cells[ci])).strip()
            public.append((q, a, cat or sheet, key))

    for n, (q, a, cat, key) in enumerate(public, start=len(seed) + 1):
        out.append(
            {
                "id": f"faq-{n:03d}",
                "question": q,
                "answer": a,
                "source": source_label,
                "category": cat,
                "key": key,
            }
        )
    stats = {
        "source": source_id,
        "raw_rows": raw_rows,
        "sheets": len(tables),
        "dropped": dropped,
        "cleaned": cleaned,
        "seed": len(seed),
        "public": len(public),
    }
    return out, stats


def _pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, round(p * (len(s) - 1)))]


# ---------------------------------------------------------------- cli


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--source", default="siheung-faq", choices=sorted(SOURCES))
    p.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    p.add_argument("--seed", type=Path, default=ROOT / "data" / "faq" / "sample_faq.json")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "faq" / "faq.jsonl")
    p.add_argument("--exclude", type=Path, default=ROOT / "data" / "faq" / "exclude_keys.txt")
    p.add_argument("--skip-download", action="store_true", help="reuse existing raw file")
    p.add_argument("--question-col", default=None, help="exact header of the question column")
    p.add_argument("--answer-col", default=None, help="exact header of the answer column")
    p.add_argument("--category-col", default=None, help="exact header of the category column")
    p.add_argument("--stats-json", type=Path, default=None, help="write statistics as JSON")
    p.add_argument("--min-rows", type=int, default=500, help="minimum final rows (else exit 4)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from app.pipeline.bm25 import BM25Retriever
    from app.pipeline.types import FaqItem

    source_id = args.source
    source = SOURCES[source_id]
    raw_path = args.raw_dir / source.filename

    if args.skip_download:
        if not raw_path.exists():
            print(f"download failed: raw file missing {raw_path}", file=sys.stderr)
            return 3
    else:
        try:
            download(source, raw_path)
        except DownloadError as e:
            print(str(e), file=sys.stderr)
            return 3

    cli_cols = (args.question_col, args.answer_col, args.category_col)
    strict = any(c is not None for c in cli_cols)
    cols = (
        args.question_col or source.question_col,
        args.answer_col or source.answer_col,
        args.category_col or source.category_col,
    )
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    tables = read_tables(raw_path, source.fmt)
    try:
        rows, stats = normalize(
            tables,
            seed,
            source_id,
            source.source_label,
            load_exclude_keys(args.exclude),
            *cols,
            strict_cols=strict,
        )
    except ColumnError as e:
        print(f"column detection failed: {e}", file=sys.stderr)
        print(f"headers: {e.headers}", file=sys.stderr)
        return 2

    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    n_bytes = len(payload.encode("utf-8"))
    items = [FaqItem(r["id"], r["question"], r["answer"], r["source"]) for r in rows]
    t0 = time.perf_counter()
    retriever = BM25Retriever(items)
    build_ms = (time.perf_counter() - t0) * 1000

    a_len = [len(r["answer"]) for r in rows]
    q_len = [len(r["question"]) for r in rows]
    stats.update(
        {
            "final": len(rows),
            "bytes": n_bytes,
            "answer_len": {"p50": _pct(a_len, 0.5), "p95": _pct(a_len, 0.95), "max": max(a_len)},
            "question_len": {"p50": _pct(q_len, 0.5)},
            "index": {
                "docs": retriever.index.n_docs,
                "vocab": len(retriever.index.df),
                "build_ms": round(build_ms, 1),
            },
        }
    )
    d, c, al, ix = stats["dropped"], stats["cleaned"], stats["answer_len"], stats["index"]
    print(f"source={source_id} raw_rows={stats['raw_rows']} sheets={stats['sheets']}")
    print("dropped " + " ".join(f"{k}={d[k]}" for k in DROP_REASONS))
    print(f"cleaned phones={c['phones']} urls={c['urls']} emails={c['emails']}")
    print(
        f"final={stats['final']} seed={stats['seed']} public={stats['public']} bytes={n_bytes} "
        f"answer_len p50={al['p50']} p95={al['p95']} max={al['max']} "
        f"question_len p50={stats['question_len']['p50']}"
    )
    print(f"index docs={ix['docs']} vocab={ix['vocab']} build_ms={ix['build_ms']}")
    if args.stats_json is not None:
        args.stats_json.parent.mkdir(parents=True, exist_ok=True)
        args.stats_json.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    if len(rows) < args.min_rows:
        print(f"too few rows: final={len(rows)} < min_rows={args.min_rows}", file=sys.stderr)
        return 4
    if n_bytes > MAX_BYTES:
        print(f"output too large: bytes={n_bytes} > {MAX_BYTES}", file=sys.stderr)
        return 4
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
