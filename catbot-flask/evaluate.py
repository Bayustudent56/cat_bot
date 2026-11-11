"""Evaluasi akurasi pencocokan intent CatBot memakai dataset CSV.

Format CSV (dengan header): ``pertanyaan,expected_intent``

Contoh pemakaian::

    python evaluate.py
    python evaluate.py --verbose
    python evaluate.py --csv evaluasi/catbot.csv --min-accuracy 0.9

Kode keluar 0 jika akurasi >= ``--min-accuracy``, selain itu 1.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from chatbot.engine import DEFAULT_KNOWLEDGE_PATH, ChatEngine

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CSV_PATH = BASE_DIR / "evaluasi" / "catbot.csv"


def load_dataset(path: str | Path = DEFAULT_CSV_PATH) -> list[dict[str, str]]:
    """Baca dataset uji dari CSV dan validasi kolom wajibnya."""
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"pertanyaan", "expected_intent"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"CSV harus memiliki kolom: {', '.join(sorted(required))}"
            )
        rows = [
            {
                "pertanyaan": (row["pertanyaan"] or "").strip(),
                "expected_intent": (row["expected_intent"] or "").strip(),
            }
            for row in reader
        ]
    return [row for row in rows if row["pertanyaan"] and row["expected_intent"]]


def evaluate(engine: ChatEngine, rows: list[dict[str, str]]) -> dict[str, Any]:
    """Jalankan engine pada setiap baris uji dan hitung akurasi."""
    results: list[dict[str, Any]] = []
    per_intent: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})

    for row in rows:
        outcome = engine.respond(row["pertanyaan"])
        expected = row["expected_intent"]
        correct = outcome.intent == expected
        per_intent[expected]["total"] += 1
        per_intent[expected]["correct"] += int(correct)
        results.append(
            {
                "pertanyaan": row["pertanyaan"],
                "expected": expected,
                "predicted": outcome.intent,
                "score": round(outcome.score, 3),
                "correct": correct,
            }
        )

    total = len(results)
    correct_total = sum(1 for r in results if r["correct"])
    return {
        "total": total,
        "correct": correct_total,
        "accuracy": (correct_total / total) if total else 0.0,
        "results": results,
        "failures": [r for r in results if not r["correct"]],
        "per_intent": {
            tag: {
                **stats,
                "accuracy": stats["correct"] / stats["total"] if stats["total"] else 0.0,
            }
            for tag, stats in sorted(per_intent.items())
        },
    }


def print_report(report: dict[str, Any], verbose: bool = False) -> None:
    """Cetak laporan evaluasi ke terminal."""
    print("=" * 78)
    print("EVALUASI AKURASI INTENT CATBOT")
    print("=" * 78)

    rows = report["results"] if verbose else report["failures"]
    if rows:
        print(f"{'':4}{'Pertanyaan':44}{'Harapan':20}{'Prediksi':20}{'Skor':>6}")
        print("-" * 78)
        for r in rows:
            mark = "OK" if r["correct"] else "XX"
            question = r["pertanyaan"][:42]
            print(f"{mark:4}{question:44}{r['expected']:20}{r['predicted']:20}{r['score']:>6.2f}")
        print("-" * 78)
    else:
        print("Semua pertanyaan uji diprediksi dengan benar.")
        print("-" * 78)

    print("Akurasi per intent:")
    for tag, stats in report["per_intent"].items():
        print(f"  {tag:24}{stats['correct']:>3}/{stats['total']:<3} ({stats['accuracy'] * 100:5.1f}%)")
    print("-" * 78)
    print(
        f"Total benar : {report['correct']}/{report['total']}\n"
        f"Akurasi     : {report['accuracy'] * 100:.1f}%"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluasi akurasi intent CatBot.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH), help="Path dataset CSV uji.")
    parser.add_argument(
        "--knowledge", default=str(DEFAULT_KNOWLEDGE_PATH), help="Path file pengetahuan JSON."
    )
    parser.add_argument(
        "--min-accuracy", type=float, default=0.9,
        help="Akurasi minimum (0-1) agar skrip berstatus sukses. Default: 0.9",
    )
    parser.add_argument("--verbose", action="store_true", help="Tampilkan semua baris uji.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    engine = ChatEngine.from_file(args.knowledge)
    report = evaluate(engine, load_dataset(args.csv))
    print_report(report, verbose=args.verbose)
    return 0 if report["accuracy"] >= args.min_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
