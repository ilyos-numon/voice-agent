import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.pipeline.types import FaqItem

_WORD_RE = re.compile(r"[0-9a-z가-힣]+")
_KEYS = ("id", "question", "answer", "source")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    tokens: list[str] = []
    for w in _WORD_RE.findall(text):
        if len(w) == 1:
            tokens.append(w)
        else:
            tokens.extend(w[i : i + 2] for i in range(len(w) - 1))
    return tokens


class BM25Index:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n_docs = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.avgdl = sum(self.doc_len) / self.n_docs if self.n_docs else 1.0
        if self.avgdl == 0:
            self.avgdl = 1.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for idx, doc in enumerate(docs):
            tf: dict[str, int] = {}
            for t in doc:
                tf[t] = tf.get(t, 0) + 1
            for t, c in tf.items():
                self.postings.setdefault(t, []).append((idx, c))
        self.df = {t: len(p) for t, p in self.postings.items()}

    def idf(self, term: str) -> float:
        df = self.df.get(term)
        if not df:
            return 0.0
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: list[str]) -> list[tuple[int, float]]:
        scores: dict[int, float] = {}
        for t in dict.fromkeys(query_tokens):
            idf = self.idf(t)
            if idf == 0.0:
                continue
            for d, tf in self.postings[t]:
                norm = tf + self.k1 * (1 - self.b + self.b * self.doc_len[d] / self.avgdl)
                scores[d] = scores.get(d, 0.0) + idf * tf * (self.k1 + 1) / norm
        hits = [(d, s) for d, s in scores.items() if s > 0]
        return sorted(hits, key=lambda h: (-h[1], h[0]))


def _to_item(path: Path, line_no: int, row: dict[str, Any]) -> FaqItem:
    for key in _KEYS:
        if key not in row:
            raise ValueError(f"{path}:{line_no}: missing {key}")
    return FaqItem(**{key: row[key] for key in _KEYS})


def load_faq_any(path: Path) -> list[FaqItem]:
    items: list[FaqItem] = []
    with open(path, encoding="utf-8") as f:
        if path.suffix == ".jsonl":
            for line_no, line in enumerate(f, start=1):
                if line.strip():
                    items.append(_to_item(path, line_no, json.loads(line)))
        else:
            for line_no, row in enumerate(json.load(f), start=1):
                items.append(_to_item(path, line_no, row))
    seen: set[str] = set()
    for it in items:
        if it.id in seen:
            raise ValueError(f"duplicate id: {it.id}")
        seen.add(it.id)
    return items


class BM25Retriever:
    def __init__(
        self, items: list[FaqItem], k1: float = 1.2, b: float = 0.75, min_score: float = 0.0
    ) -> None:
        self.items = list(items)
        self.min_score = min_score
        self.index = BM25Index([tokenize(it.question) for it in self.items], k1, b)

    @classmethod
    def from_path(cls, faq_path: Path, **kw: float) -> "BM25Retriever":
        return cls(load_faq_any(faq_path), **kw)

    def search(self, query: str, top_k: int = 3) -> list[FaqItem]:
        hits = self.index.score(tokenize(query))
        return [self.items[i] for i, s in hits if s > self.min_score][:top_k]
