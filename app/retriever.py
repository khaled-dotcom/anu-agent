"""Lexical retriever tuned for Arabic + English mixed content.

No embedding provider needed: BM25 over a normalized Arabic index is strong
enough for a knowledge base of a few hundred chunks, costs nothing, and runs
offline. Swap in vector search later if the KB grows past ~2000 chunks.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "knowledge.json"

# Arabic diacritics, tatweel, and Quranic marks.
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640\u06D6-\u06ED]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06FF]+", re.UNICODE)
_ARABIC_PREFIX = re.compile(r"^(?:وال|بال|كال|فال|ال|لل|و|ف|ب|ك|ل)(?=\w{3,})")

# Without this, "الاسكندريه" and "الإسكندرية" are two different tokens and
# lexical search silently fails on half the student questions.
_FOLD = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
        "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }
)

# Students type colloquial Egyptian; the site is written in formal Arabic and
# English. This bridge is the single highest-impact piece of the retriever.
SYNONYMS: dict[str, list[str]] = {
    "مصاريف": ["الرسوم", "الرسوم الدراسية", "المصروفات", "tuition", "fees"],
    "فلوس": ["الرسوم", "المصروفات", "tuition"],
    "تكلفه": ["الرسوم", "المصروفات", "tuition"],
    "المجموع": ["الحد الادني", "درجات", "القبول", "admission"],
    "تنسيق": ["القبول", "الحد الادني", "admission"],
    "كليات": ["البرامج", "مجالات الدراسه", "programs", "study fields"],
    "كليه": ["البرامج", "برنامج", "program"],
    "قسم": ["برنامج", "program"],
    "تقديم": ["التسجيل", "القبول", "admission", "apply"],
    "اقدم": ["التسجيل", "القبول", "admission"],
    "منحه": ["المنح", "scholarship", "الدعم المالي"],
    "منح": ["scholarship", "الدعم المالي"],
    "سكن": ["الاقامه", "housing", "dormitory"],
    "اسنان": ["طب الفم والاسنان", "dentistry"],
    "صيدله": ["الصيدله", "pharmacy"],
    "هندسه": ["البرامج الهندسيه", "engineering"],
    "حاسب": ["علوم الحاسب", "computer science"],
    "كمبيوتر": ["علوم الحاسب", "computer science"],
    "بزنس": ["ادارة الاعمال", "business"],
    "تجاره": ["ادارة الاعمال", "business"],
    "عنوان": ["الحرم الجامعي", "ابيس", "campus", "location"],
    "مكان": ["الحرم الجامعي", "ابيس", "campus"],
    "تليفون": ["الهاتف", "رقم", "contact"],
    "ايميل": ["البريد الالكتروني", "email"],
}


def normalize(text: str) -> str:
    text = _DIACRITICS.sub("", text or "")
    text = text.translate(_FOLD)
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _NON_WORD.split(normalize(text)):
        if len(raw) < 2:
            continue
        tokens.append(raw)
        stripped = _ARABIC_PREFIX.sub("", raw)
        if stripped != raw and len(stripped) >= 3:
            tokens.append(stripped)
    return tokens


def expand_query(text: str) -> str:
    normalized = normalize(text)
    extras = [
        " ".join(alts)
        for key, alts in SYNONYMS.items()
        if normalize(key) in normalized
    ]
    return f"{text} {' '.join(extras)}" if extras else text


class Retriever:
    """BM25 over knowledge chunks. Reloads from disk when the file changes."""

    K1 = 1.5
    B = 0.75

    def __init__(self, path: Path = DATA_FILE) -> None:
        self.path = path
        self._mtime = 0.0
        self.chunks: list[dict[str, Any]] = []
        self._tokens: list[Counter] = []
        self._lengths: list[int] = []
        self._idf: dict[str, float] = {}
        self._avg_len = 1.0
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.chunks = []
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.chunks = payload.get("chunks", [])
        self.last_sync = payload.get("last_sync", "غير معروف")
        self._mtime = self.path.stat().st_mtime
        self._build_index()

    def _maybe_reload(self) -> None:
        if self.path.exists() and self.path.stat().st_mtime != self._mtime:
            self.reload()

    def _build_index(self) -> None:
        self._tokens = []
        self._lengths = []
        df: Counter = Counter()
        for chunk in self.chunks:
            body = f"{chunk.get('title', '')} {chunk.get('title', '')} {chunk.get('text', '')}"
            counts = Counter(tokenize(body))
            self._tokens.append(counts)
            self._lengths.append(sum(counts.values()) or 1)
            df.update(counts.keys())

        n = len(self.chunks) or 1
        self._avg_len = sum(self._lengths) / n if self._lengths else 1.0
        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 5, min_score: float = 1.5):
        self._maybe_reload()
        if not self.chunks:
            return []

        terms = tokenize(expand_query(query))
        if not terms:
            return []

        scored = []
        for idx, counts in enumerate(self._tokens):
            length = self._lengths[idx]
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                denom = tf + self.K1 * (1 - self.B + self.B * length / self._avg_len)
                score += self._idf.get(term, 0.0) * (tf * (self.K1 + 1)) / denom
            if score > 0:
                scored.append((score, idx))

        scored.sort(reverse=True)
        return [
            {**self.chunks[idx], "score": round(score, 3)}
            for score, idx in scored[:top_k]
            if score >= min_score
        ]


def build_context(hits: list[dict[str, Any]]) -> str:
    """Render retrieved chunks into the <context> block for the model."""
    if not hits:
        return "لا توجد مقاطع مطابقة."
    blocks = []
    for i, hit in enumerate(hits, 1):
        blocks.append(
            f"[{i}] العنوان: {hit.get('title', '')}\n"
            f"المصدر: {hit.get('url', '')}\n"
            f"النص: {hit.get('text', '').strip()}"
        )
    return "\n\n".join(blocks)
