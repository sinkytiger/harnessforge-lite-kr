"""BM25 search over line-aligned chunks, with Hangul character bigrams.

Korean particles attach to words ("영업이익은", "매출액이"), so whole-word matching misses most hits.
Character bigrams of Hangul runs are a standard, dependency-free fix. Numbers are indexed without
thousands separators, so "12,345" and "12345" match.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d[\d,\.]*")
_SECTION = re.compile(r"^((?:X{0,1}(?:IX|IV|V?I{0,3}))\.\s|\d+\.\s|[가-하]\.\s)")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.finditer(text or ""):
        w = m.group(0)
        if w[0].isdigit():
            out.append(w.replace(",", "").rstrip("."))
        elif "가" <= w[0] <= "힣":
            out.extend([w] if len(w) == 1 else [w[i:i + 2] for i in range(len(w) - 1)])
        else:
            out.append(w.lower())
    return out


@dataclass
class Chunk:
    doc_id: str
    start: int
    end: int
    section: str
    lines: list[tuple[int, str, str]]  # (offset, line, section heading)


class Index:
    def __init__(self, docs: list[dict], chunk_chars: int = 480, k1: float = 1.2, b: float = 0.75) -> None:
        self.docs = {d["doc_id"]: d for d in docs}
        self.k1, self.b = k1, b
        self.chunks: list[Chunk] = []
        for d in docs:
            self._chunk(d, chunk_chars)
        self.tf: list[Counter] = []
        df: Counter = Counter()
        for c in self.chunks:
            # Contextual chunk header: tables do not repeat the company name or the report type,
            # so each chunk is indexed with its filing title and section heading.
            d = self.docs[c.doc_id]
            head = f"{d['company']} {d['report']} {c.section}"
            tf = Counter(tokenize(head + " " + " ".join(line for _, line, _ in c.lines)))
            self.tf.append(tf)
            df.update(tf.keys())
        self.dl = [sum(tf.values()) for tf in self.tf]
        self.avgdl = sum(self.dl) / max(len(self.dl), 1)
        n = len(self.chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def _chunk(self, doc: dict, chunk_chars: int) -> None:
        text = doc["text"]
        pos, section = 0, ""
        cur: list[tuple[int, str]] = []
        size = 0
        top = ""
        for line in text.split("\n"):
            if _SECTION.match(line) and len(line) < 60:
                if re.match(r"^[IVX]+\.\s", line):
                    top = line.split(" ")[0]
                    section = line
                else:
                    section = f"{top} {line}".strip()
            if line.strip():
                cur.append((pos, line, section))
                size += len(line) + 1
            if size >= chunk_chars:
                self.chunks.append(Chunk(doc["doc_id"], cur[0][0], pos + len(line), section, cur))
                cur, size = [], 0
            pos += len(line) + 1
        if cur:
            self.chunks.append(Chunk(doc["doc_id"], cur[0][0], pos, section, cur))

    def search(self, query: str, k: int = 5, company: str | None = None, doc_id: str | None = None,
               snippet_chars: int = 160) -> list[dict]:
        q = tokenize(query)
        if not q:
            return []
        qset = Counter(q)
        scores = []
        for i, c in enumerate(self.chunks):
            d = self.docs[c.doc_id]
            if doc_id and c.doc_id != doc_id:
                continue
            if company and company not in d["company"] and company != d.get("company_key"):
                continue
            tf, dl = self.tf[i], self.dl[i]
            s = 0.0
            for t, qn in qset.items():
                f = tf.get(t, 0)
                if f:
                    s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: -x[0])
        out = []
        for s, i in scores[:k]:
            c = self.chunks[i]
            best_off, best_line, best_sec, best = c.lines[0][0], c.lines[0][1], c.lines[0][2], -1
            for off, line, sec in c.lines:
                ov = sum(1 for t in tokenize(line) if t in qset)
                if ov > best:
                    best_off, best_line, best_sec, best = off, line, sec, ov
            out.append({"doc_id": c.doc_id, "title": _title(self.docs[c.doc_id]), "section": best_sec,
                        "offset": best_off, "snippet": best_line[:snippet_chars], "score": round(s, 3)})
        return out

    def regex(self, pattern: str, k: int = 5, company: str | None = None, doc_id: str | None = None,
              snippet_chars: int = 160) -> list[dict]:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"bad regex: {exc}") from exc
        out = []
        for c in self.chunks:
            d = self.docs[c.doc_id]
            if doc_id and c.doc_id != doc_id:
                continue
            if company and company not in d["company"]:
                continue
            for off, line, sec in c.lines:
                if rx.search(line):
                    out.append({"doc_id": c.doc_id, "title": _title(d), "section": sec, "offset": off,
                                "snippet": line[:snippet_chars], "score": 1.0})
                    if len(out) >= k:
                        return out
        return out


def _title(d: dict) -> str:
    return f"{d['company']} | {d['report']} | 제출 {d['filed']}"
