"""Unit test mesin pencocokan intent CatBot."""

import json
import random

import pytest

import evaluate
from chatbot.engine import (
    DEFAULT_KNOWLEDGE_PATH,
    ChatEngine,
    normalize_text,
    tokenize,
)

EXPECTED_COUNTS = {
    # tag: (jumlah pola, jumlah respons)
    "salam": (12, 3),
    "makanan_kucing": (11, 4),
    "jadwal_makan": (8, 4),
    "minum_kucing": (7, 5),
    "kebersihan_kucing": (8, 4),
    "mandi_kucing": (7, 4),
    "perawatan_bulu": (7, 4),
    "litter_box": (8, 4),
    "kesehatan_kucing": (9, 4),
    "darurat_kesehatan": (9, 2),
    "perawatan_anak_kucing": (8, 4),
    "perilaku_kucing": (9, 4),
    "penutup": (9, 3),
    "fallback": (0, 3),
}


@pytest.fixture(scope="module")
def engine():
    return ChatEngine.from_file(DEFAULT_KNOWLEDGE_PATH, rng=random.Random(42))


# ---------------------------------------------------------------- knowledge
def test_knowledge_has_14_intents_with_expected_counts(engine):
    assert set(engine.intents) == set(EXPECTED_COUNTS)
    for tag, (n_patterns, n_responses) in EXPECTED_COUNTS.items():
        intent = engine.intents[tag]
        assert len(intent.patterns) == n_patterns, tag
        assert len(intent.responses) == n_responses, tag


def test_response_keywords_align_with_responses():
    with open(DEFAULT_KNOWLEDGE_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    for intent in data["intents"]:
        if "response_keywords" in intent:
            assert len(intent["response_keywords"]) == len(intent["responses"]), intent["tag"]


def test_invalid_knowledge_is_rejected():
    with pytest.raises(ValueError):
        ChatEngine({"intents": []})
    with pytest.raises(ValueError):  # tanpa fallback
        ChatEngine({"intents": [{"tag": "salam", "patterns": ["halo"], "responses": ["hai"]}]})


# ------------------------------------------------------------- normalization
def test_normalize_text():
    assert normalize_text("  Halo,   CatBot!!  ") == "halo catbot"
    assert normalize_text("Garuk-garuk terus?") == "garuk garuk terus"


def test_tokenize_drops_stopwords_and_stems():
    tokens = tokenize("Apakah kucingnya boleh dimandikan?")
    assert "kucing" in tokens and "mandi" in tokens
    assert "apakah" not in tokens


# -------------------------------------------------------------- exact match
def test_every_pattern_matches_its_own_intent(engine):
    for tag, intent in engine.intents.items():
        for pattern in intent.patterns:
            result = engine.respond(pattern.text)
            assert result.intent == tag, f"'{pattern.text}' -> {result.intent}, harapan {tag}"


def test_exact_match_has_full_score(engine):
    result = engine.respond("Hai")
    assert result.intent == "salam"
    assert result.score == 1.0
    assert result.method == "exact"


def test_case_and_punctuation_insensitive(engine):
    assert engine.respond("MAKANAN APA YANG BAGUS UNTUK KUCING").intent == "makanan_kucing"
    assert engine.respond("  seberapa sering litter box dibersihkan  ").intent == "litter_box"


# --------------------------------------------------------------- paraphrases
@pytest.mark.parametrize(
    "question, expected",
    [
        ("Halo, selamat pagi CatBot", "salam"),
        ("Kucing boleh makan tuna?", "makanan_kucing"),
        ("Rekomendasi makanan kucing", "makanan_kucing"),
        ("Jadwal makan kucing yang baik", "jadwal_makan"),
        ("Bagaimana supaya kucing mau minum?", "minum_kucing"),
        ("Cara membersihkan mata kucing", "kebersihan_kucing"),
        ("Cara memandikan kucing yang benar", "mandi_kucing"),
        ("Bulu kucing saya kusut harus bagaimana?", "perawatan_bulu"),
        ("Kucing saya buang air sembarangan", "litter_box"),
        ("Kapan kucing harus divaksin?", "kesehatan_kucing"),
        ("Kucing saya sulit bernapas", "darurat_kesehatan"),
        ("Kapan anak kucing boleh dipisah dari induknya?", "perawatan_anak_kucing"),
        ("Kenapa kucing mendengkur?", "perilaku_kucing"),
        ("Makasih banyak ya", "penutup"),
    ],
)
def test_paraphrased_questions(engine, question, expected):
    assert engine.respond(question).intent == expected


def test_typo_is_tolerated(engine):
    assert engine.respond("kucign saya bersin bersin").intent == "kesehatan_kucing"


def test_urgent_keywords_override_everything(engine):
    result = engine.respond("tolong, kucing saya keracunan setelah makan makanan basah")
    assert result.intent == "darurat_kesehatan"
    assert result.method == "urgent_keyword"


def test_chocolate_paraphrase_is_emergency(engine):
    assert engine.respond("kucing saya makan coklat").intent == "darurat_kesehatan"


# ------------------------------------------------------------------ fallback
@pytest.mark.parametrize(
    "question",
    ["Siapa presiden Indonesia?", "Bagaimana cuaca hari ini?", "asdfgh", "", "   ", "???", "kucing"],
)
def test_out_of_scope_goes_to_fallback(engine, question):
    result = engine.respond(question)
    assert result.intent == "fallback"
    assert result.is_fallback is True
    assert result.response in engine.intents["fallback"].responses


# ----------------------------------------------------------------- responses
def test_response_comes_from_matched_intent(engine):
    result = engine.respond("Berapa kali kucing makan dalam sehari?")
    assert result.response in engine.intents["jadwal_makan"].responses


@pytest.mark.parametrize(
    "question, expected_fragment",
    [
        ("Kucing boleh makan tuna?", "Ikan dan ayam boleh diberikan"),
        ("Makanan manusia apa yang tidak boleh diberikan ke kucing?", "bawang merah"),
        ("Cara memotong kuku kucing?", "Potong hanya ujung kuku"),
        ("Cara membersihkan telinga kucing?", "cotton bud"),
        ("Cara mengatasi hairball?", "hairball"),
        ("Kenapa kucing menggaruk sofa?", "scratching post"),
        ("Kucing saya kejang", "Tetap tenang"),
    ],
)
def test_relevant_response_is_selected(engine, question, expected_fragment):
    assert expected_fragment in engine.respond(question).response


def test_random_mode_is_reproducible_with_seed():
    first = ChatEngine.from_file(rng=random.Random(7)).respond("Halo").response
    second = ChatEngine.from_file(rng=random.Random(7)).respond("Halo").response
    assert first == second


def test_result_to_dict(engine):
    data = engine.respond("Hai").to_dict()
    assert {"intent", "score", "response", "is_fallback", "method", "candidates"} <= set(data)


# ---------------------------------------------------------------- evaluation
def test_csv_dataset_has_at_least_30_rows():
    assert len(evaluate.load_dataset()) >= 30


def test_csv_dataset_covers_all_intents(engine):
    expected = {row["expected_intent"] for row in evaluate.load_dataset()}
    assert expected == set(engine.intents)


def test_csv_accuracy_is_high(engine):
    report = evaluate.evaluate(engine, evaluate.load_dataset())
    assert report["accuracy"] >= 0.9, report["failures"]
