"""Mesin pencocokan intent CatBot (rule-based).

Alur kerja satu pertanyaan:

1. Teks dinormalisasi (huruf kecil, tanda baca dibuang, spasi dirapikan).
2. Jika memuat kata kunci darurat (mis. "keracunan", "kejang"), intent
   ``darurat_kesehatan`` langsung dipilih demi keselamatan.
3. Selain itu, setiap pola pada setiap intent diberi skor gabungan:
   - token overlap berbobot IDF (kata langka lebih menentukan), dan
   - kemiripan karakter memakai ``difflib.SequenceMatcher``.
4. Intent dengan skor tertinggi dipilih jika skornya >= ambang batas;
   jika tidak, intent ``fallback`` dipakai.
5. Respons dipilih: berdasarkan kata kunci yang paling relevan
   (``response_mode = relevant``) atau acak (``response_mode = random``).
"""

from __future__ import annotations

import json
import math
import random
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Any

DEFAULT_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parent.parent / "themes" / "catbot.json"
)
FALLBACK_TAG = "fallback"
URGENT_TAG = "darurat_kesehatan"
DEFAULT_THRESHOLD = 0.5

# Kata yang tidak membawa makna pembeda antar intent.
STOPWORDS = frozenset(
    {
        "yang", "di", "ke", "dari", "dong", "ya", "nih", "sih", "deh", "kok",
        "tuh", "itu", "ini", "untuk", "dengan", "dan", "atau", "saya", "aku",
        "kamu", "apakah", "tolong", "mohon", "bot", "catbot", "kah", "pun",
    }
)

# Normalisasi bentuk kata turunan yang sering muncul di domain perawatan kucing.
ALIASES = {
    "memandikan": "mandi", "dimandikan": "mandi", "memandikannya": "mandi",
    "mandiin": "mandi", "memakan": "makan", "dimakan": "makan",
    "dikasih": "kasih", "diberi": "beri", "diberikan": "beri", "memberi": "beri",
    "memberikan": "beri", "membersihkan": "bersih", "dibersihkan": "bersih",
    "bersihkan": "bersih", "membersihkannya": "bersih", "menyisir": "sisir",
    "disisir": "sisir", "memotong": "potong", "dipotong": "potong",
    "menggaruk": "garuk", "mencakar": "cakar", "menggigit": "gigit",
    "mengigit": "gigit", "digigit": "gigit", "divaksin": "vaksin",
    "vaksinasi": "vaksin", "disteril": "steril", "sterilisasi": "steril",
    "mengeong": "eong", "ngeong": "eong", "mendengkur": "dengkur",
    "mendesis": "desis", "menginjak": "injak", "merawat": "rawat",
    "perawatan": "rawat", "dirawat": "rawat", "minum": "minum",
    "diminum": "minum", "meminum": "minum", "diganti": "ganti",
    "mengganti": "ganti", "menghangatkan": "hangat", "dipisah": "pisah",
    "memisahkan": "pisah", "dipisahkan": "pisah", "bernafas": "bernapas",
    "nafas": "napas", "coklat": "cokelat", "shampo": "sampo", "shampoo": "sampo",
    "sampoo": "sampo", "kutuan": "kutu", "kejang-kejang": "kejang",
    "dokter": "dokter", "vet": "dokter",
}

_SUFFIXES = ("nya", "kah", "lah")


def normalize_text(text: Any) -> str:
    """Ubah teks ke huruf kecil, buang tanda baca, rapikan spasi."""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = text.replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _stem(token: str) -> str:
    """Stemming ringan: alias domain + pembuangan akhiran -nya/-kah/-lah."""
    token = ALIASES.get(token, token)
    for suffix in _SUFFIXES:
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return ALIASES.get(token, token)


def tokenize(text: Any, drop_stopwords: bool = True) -> list[str]:
    """Pecah teks menjadi token bersih (sudah di-stem, tanpa stopword)."""
    tokens = [_stem(t) for t in normalize_text(text).split()]
    if drop_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens


def _contains_keyword(padded_text: str, keyword: str) -> bool:
    """Cek keyword pada teks ternormalisasi (sudah diberi spasi di tepi).

    Keyword pendek (<= 3 huruf) wajib cocok sebagai kata utuh agar tidak
    salah cocok di tengah kata lain (mis. "asi" pada "kasih").
    """
    keyword = normalize_text(keyword)
    if not keyword:
        return False
    if len(keyword) <= 3:
        return f" {keyword} " in padded_text
    return keyword in padded_text


@dataclass(frozen=True)
class _Pattern:
    text: str
    normalized: str
    tokens: frozenset[str]


@dataclass
class Intent:
    tag: str
    description: str
    response_mode: str
    patterns: list[_Pattern]
    responses: list[str]
    response_keywords: list[list[str]] = field(default_factory=list)


@dataclass
class ChatResult:
    """Hasil pemrosesan satu pesan pengguna."""

    intent: str
    score: float
    response: str
    matched_pattern: str | None
    is_fallback: bool
    method: str
    candidates: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "score": round(self.score, 4),
            "response": self.response,
            "matched_pattern": self.matched_pattern,
            "is_fallback": self.is_fallback,
            "method": self.method,
            "candidates": [(tag, round(s, 4)) for tag, s in self.candidates],
        }


class ChatEngine:
    """Mesin chatbot berbasis aturan yang dibangun dari file pengetahuan JSON."""

    def __init__(
        self,
        knowledge: dict[str, Any],
        threshold: float | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.rng = rng or random.Random()
        self.name: str = knowledge.get("name", "CatBot")
        self.description: str = knowledge.get("description", "")
        self.disclaimer: str = knowledge.get("disclaimer", "")
        self.quick_replies: list[str] = list(knowledge.get("quick_replies", []))
        self.urgent_keywords: list[str] = list(knowledge.get("urgent_keywords", []))
        self.threshold: float = float(
            threshold if threshold is not None
            else knowledge.get("threshold", DEFAULT_THRESHOLD)
        )
        self.intents: dict[str, Intent] = self._load_intents(knowledge)
        if FALLBACK_TAG not in self.intents:
            raise ValueError(f"Intent '{FALLBACK_TAG}' wajib ada pada basis pengetahuan.")

        self._build_vocabulary()

    # ------------------------------------------------------------------ setup
    @classmethod
    def from_file(
        cls,
        path: str | Path = DEFAULT_KNOWLEDGE_PATH,
        threshold: float | None = None,
        rng: random.Random | None = None,
    ) -> "ChatEngine":
        with open(path, encoding="utf-8") as handle:
            knowledge = json.load(handle)
        return cls(knowledge, threshold=threshold, rng=rng)

    @staticmethod
    def _load_intents(knowledge: dict[str, Any]) -> dict[str, Intent]:
        raw_intents = knowledge.get("intents")
        if not isinstance(raw_intents, list) or not raw_intents:
            raise ValueError("Basis pengetahuan harus memiliki daftar 'intents'.")

        intents: dict[str, Intent] = {}
        for raw in raw_intents:
            tag = raw.get("tag")
            if not tag:
                raise ValueError("Setiap intent harus memiliki 'tag'.")
            if tag in intents:
                raise ValueError(f"Tag intent ganda: {tag}")
            responses = list(raw.get("responses", []))
            if not responses:
                raise ValueError(f"Intent '{tag}' harus memiliki minimal satu respons.")
            keywords = [list(k) for k in raw.get("response_keywords", [])]
            if keywords and len(keywords) != len(responses):
                raise ValueError(
                    f"Intent '{tag}': jumlah 'response_keywords' harus sama dengan 'responses'."
                )
            patterns = [
                _Pattern(text=p, normalized=normalize_text(p), tokens=frozenset(tokenize(p)))
                for p in raw.get("patterns", [])
            ]
            intents[tag] = Intent(
                tag=tag,
                description=raw.get("description", ""),
                response_mode=raw.get("response_mode", "random"),
                patterns=patterns,
                responses=responses,
                response_keywords=keywords,
            )
        return intents

    def _build_vocabulary(self) -> None:
        """Hitung bobot IDF tiap token berdasarkan jumlah intent yang memuatnya."""
        matchable = [i for i in self.intents.values() if i.patterns]
        n_intents = max(len(matchable), 1)
        doc_freq: dict[str, int] = {}
        for intent in matchable:
            seen: set[str] = set()
            for pattern in intent.patterns:
                seen.update(pattern.tokens)
            for token in seen:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        self._idf = {
            token: math.log(1 + n_intents / df) for token, df in doc_freq.items()
        }
        # Token yang muncul di separuh lebih intent (mis. "kucing") terlalu umum
        # untuk menjadi satu-satunya dasar pencocokan.
        self._generic = {t for t, df in doc_freq.items() if df >= 0.5 * n_intents}
        # Kata yang tidak dikenal dianggap cukup "berbobot" agar menurunkan skor.
        self._unknown_idf = math.log(1 + n_intents)
        self._vocabulary = sorted(self._idf)

    # --------------------------------------------------------------- matching
    def _resolve_token(self, token: str) -> str:
        """Perbaiki salah ketik ringan dengan mencocokkan ke kosakata."""
        if token in self._idf or len(token) < 4:
            return token
        close = get_close_matches(token, self._vocabulary, n=1, cutoff=0.82)
        return close[0] if close else token

    def _weight(self, token: str) -> float:
        return self._idf.get(token, self._unknown_idf)

    def _score_pattern(
        self, query_tokens: set[str], query_norm: str, pattern: _Pattern
    ) -> float:
        if query_norm == pattern.normalized:
            return 1.0
        if not query_tokens or not pattern.tokens:
            return 0.0

        common = query_tokens & pattern.tokens
        if not common or common <= self._generic:
            return 0.0

        shared = sum(self._weight(t) for t in common)
        query_total = sum(self._weight(t) for t in query_tokens)
        pattern_total = sum(self._weight(t) for t in pattern.tokens)

        coverage = shared / query_total if query_total else 0.0
        precision = shared / pattern_total if pattern_total else 0.0
        token_score = 0.7 * coverage + 0.3 * precision
        sequence_score = SequenceMatcher(None, query_norm, pattern.normalized).ratio()
        return 0.7 * token_score + 0.3 * sequence_score

    def _is_urgent(self, query_norm: str) -> bool:
        padded = f" {query_norm} "
        return any(_contains_keyword(padded, kw) for kw in self.urgent_keywords)

    def match(self, text: str) -> tuple[str, float, str | None, str, list[tuple[str, float]]]:
        """Kembalikan (tag, skor, pola cocok, metode, kandidat teratas)."""
        query_norm = normalize_text(text)
        if not query_norm:
            return FALLBACK_TAG, 0.0, None, "empty", []

        if URGENT_TAG in self.intents and self._is_urgent(query_norm):
            return URGENT_TAG, 1.0, None, "urgent_keyword", [(URGENT_TAG, 1.0)]

        query_tokens = {self._resolve_token(t) for t in tokenize(query_norm)}
        if not query_tokens:
            return FALLBACK_TAG, 0.0, None, "no_tokens", []

        best_per_intent: dict[str, tuple[float, str]] = {}
        for tag, intent in self.intents.items():
            for pattern in intent.patterns:
                score = self._score_pattern(query_tokens, query_norm, pattern)
                if score > best_per_intent.get(tag, (-1.0, ""))[0]:
                    best_per_intent[tag] = (score, pattern.text)

        ranked = sorted(
            ((tag, score) for tag, (score, _) in best_per_intent.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        candidates = ranked[:3]
        if not ranked:
            return FALLBACK_TAG, 0.0, None, "no_patterns", []

        best_tag, best_score = ranked[0]
        if best_score < self.threshold:
            return FALLBACK_TAG, best_score, None, "below_threshold", candidates
        method = "exact" if best_score >= 1.0 else "similarity"
        return best_tag, best_score, best_per_intent[best_tag][1], method, candidates

    # -------------------------------------------------------------- responses
    def _pick_response(self, intent: Intent, query_norm: str) -> str:
        if intent.response_mode == "relevant" and intent.response_keywords:
            padded = f" {query_norm} "
            hits = [
                sum(1 for kw in keywords if _contains_keyword(padded, kw))
                for keywords in intent.response_keywords
            ]
            best = max(hits)
            return intent.responses[hits.index(best)] if best > 0 else intent.responses[0]
        return self.rng.choice(intent.responses)

    def respond(self, text: str) -> ChatResult:
        """Proses pesan pengguna dan kembalikan ``ChatResult`` lengkap."""
        tag, score, pattern, method, candidates = self.match(text)
        intent = self.intents[tag]
        response = self._pick_response(intent, normalize_text(text))
        return ChatResult(
            intent=tag,
            score=score,
            response=response,
            matched_pattern=pattern,
            is_fallback=(tag == FALLBACK_TAG),
            method=method,
            candidates=candidates,
        )

    # ---------------------------------------------------------------- helpers
    def intent_summary(self) -> list[dict[str, Any]]:
        """Ringkasan intent (tag, deskripsi, jumlah pola & respons)."""
        return [
            {
                "tag": i.tag,
                "description": i.description,
                "patterns": len(i.patterns),
                "responses": len(i.responses),
            }
            for i in self.intents.values()
        ]
