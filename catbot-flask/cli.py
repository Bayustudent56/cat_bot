"""Antarmuka CatBot di terminal (CLI).

Contoh::

    python cli.py
    python cli.py --debug          # tampilkan intent, skor, dan pola yang cocok
    python cli.py --log            # simpan percakapan ke database SQLite
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from chatbot import database as db
from chatbot.engine import DEFAULT_KNOWLEDGE_PATH, ChatEngine

EXIT_COMMANDS = {"keluar", "exit", "quit", "q"}
DEFAULT_DB = os.environ.get(
    "CATBOT_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "catbot.db"),
)

BANNER = """\
=====================================================
  CatBot - Chatbot Perawatan Dasar Kucing
=====================================================
Tanyakan seputar makanan, kebersihan, dan perawatan kucing.
Ketik 'keluar' untuk mengakhiri percakapan.
Catatan: CatBot bukan pengganti dokter hewan.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CatBot di terminal.")
    parser.add_argument("--knowledge", default=str(DEFAULT_KNOWLEDGE_PATH))
    parser.add_argument("--debug", action="store_true", help="Tampilkan detail pencocokan.")
    parser.add_argument("--log", action="store_true", help="Simpan percakapan ke SQLite.")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path database SQLite untuk --log.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    engine = ChatEngine.from_file(args.knowledge)
    session_id = f"cli-{uuid.uuid4().hex[:12]}"
    if args.log:
        db.init_db(args.db)

    print(BANNER)
    while True:
        try:
            user_input = input("Kamu    : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCatBot  : Sampai jumpa! Peluk hangat untuk kucingmu.")
            return 0

        if not user_input:
            continue
        if user_input.lower() in EXIT_COMMANDS:
            print("CatBot  : Sampai jumpa! Peluk hangat untuk kucingmu.")
            return 0

        result = engine.respond(user_input)
        print(f"CatBot  : {result.response}")
        if args.debug:
            print(
                f"          [intent={result.intent} skor={result.score:.2f} "
                f"metode={result.method} pola={result.matched_pattern!r}]"
            )
        print()

        if args.log:
            db.log_conversation(
                args.db,
                session_id=session_id,
                user_message=user_input,
                intent=result.intent,
                score=result.score,
                response=result.response,
                is_fallback=result.is_fallback,
                matched_pattern=result.matched_pattern,
            )


if __name__ == "__main__":
    sys.exit(main())
