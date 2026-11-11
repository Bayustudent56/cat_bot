"""CatBot - aplikasi web Flask (halaman web, API JSON, dan dashboard admin).

Menjalankan aplikasi::

    python app.py

Variabel lingkungan (opsional):

    CATBOT_DB           path file SQLite (default: instance/catbot.db)
    CATBOT_ADMIN_TOKEN  token untuk membuka /admin (sangat disarankan di produksi)
    CATBOT_SECRET_KEY   secret key Flask
    PORT / HOST         port dan host server pengembangan
"""

from __future__ import annotations

import hmac
import os
import re
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

import evaluate as evaluation
from chatbot import database as db
from chatbot.engine import DEFAULT_KNOWLEDGE_PATH, ChatEngine

BASE_DIR = Path(__file__).resolve().parent
MAX_MESSAGE_LENGTH = 500
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

TOPICS = [
    {
        "title": "Makanan",
        "icon": "🍗",
        "text": "Jenis makanan yang cocok, makanan berbahaya, jadwal makan, porsi, dan air minum.",
    },
    {
        "title": "Kebersihan",
        "icon": "🛁",
        "text": "Mata, telinga, gigi, kuku, kutu, mandi, dan menjaga litter box tetap bersih.",
    },
    {
        "title": "Perawatan",
        "icon": "🪮",
        "text": "Menyisir bulu, hairball, anak kucing, kesehatan dasar, dan memahami perilaku kucing.",
    },
]


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Application factory: membuat dan mengonfigurasi aplikasi Flask."""
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("CATBOT_SECRET_KEY", "dev-ganti-di-produksi"),
        DATABASE=os.environ.get("CATBOT_DB", str(BASE_DIR / "instance" / "catbot.db")),
        KNOWLEDGE_FILE=str(DEFAULT_KNOWLEDGE_PATH),
        EVAL_FILE=str(evaluation.DEFAULT_CSV_PATH),
        ADMIN_TOKEN=os.environ.get("CATBOT_ADMIN_TOKEN", ""),
        ADMIN_LIST_LIMIT=50,
    )
    if test_config:
        app.config.update(test_config)

    app.json.ensure_ascii = False
    app.json.sort_keys = False

    db.init_db(app.config["DATABASE"])
    engine = ChatEngine.from_file(app.config["KNOWLEDGE_FILE"])
    app.extensions["catbot_engine"] = engine

    register_routes(app, engine)
    register_error_handlers(app)
    return app


def _is_admin_authorized(app: Flask) -> bool:
    """Admin terbuka jika token belum diatur; jika diatur, token wajib cocok."""
    expected = app.config.get("ADMIN_TOKEN", "")
    if not expected:
        return True
    provided = request.headers.get("X-Admin-Token") or request.args.get("token", "")
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def register_routes(app: Flask, engine: ChatEngine) -> None:
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            engine=engine,
            topics=TOPICS,
            intent_count=len(engine.intents),
        )

    @app.get("/chat")
    def chat():
        return render_template(
            "chat.html",
            engine=engine,
            quick_replies=engine.quick_replies,
            max_length=MAX_MESSAGE_LENGTH,
        )

    @app.post("/api/chat")
    def api_chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Body harus berupa JSON object."), 400

        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return jsonify(error="Field 'message' wajib diisi."), 400
        message = message.strip()
        if len(message) > MAX_MESSAGE_LENGTH:
            return (
                jsonify(error=f"Pesan terlalu panjang (maksimal {MAX_MESSAGE_LENGTH} karakter)."),
                400,
            )

        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not SESSION_ID_PATTERN.match(session_id):
            session_id = uuid.uuid4().hex

        result = engine.respond(message)
        db.log_conversation(
            app.config["DATABASE"],
            session_id=session_id,
            user_message=message,
            intent=result.intent,
            score=result.score,
            response=result.response,
            is_fallback=result.is_fallback,
            matched_pattern=result.matched_pattern,
        )
        return jsonify(
            reply=result.response,
            intent=result.intent,
            score=round(result.score, 3),
            is_fallback=result.is_fallback,
            session_id=session_id,
        )

    @app.get("/api/intents")
    def api_intents():
        return jsonify(intents=engine.intent_summary(), quick_replies=engine.quick_replies)

    @app.get("/health")
    def health():
        return jsonify(status="ok", intents=len(engine.intents))

    @app.get("/admin")
    def admin():
        if not _is_admin_authorized(app):
            return (
                render_template("404.html", engine=engine, message="Halaman tidak ditemukan."),
                404,
            )

        limit = int(app.config["ADMIN_LIST_LIMIT"])
        db_path = app.config["DATABASE"]
        stats = db.get_stats(db_path)
        try:
            report = evaluation.evaluate(
                engine, evaluation.load_dataset(app.config["EVAL_FILE"])
            )
        except (OSError, ValueError):
            report = None

        return render_template(
            "admin.html",
            engine=engine,
            stats=stats,
            conversations=db.get_recent_conversations(db_path, limit),
            fallbacks=db.get_fallback_questions(db_path, limit),
            report=report,
            token_required=bool(app.config.get("ADMIN_TOKEN")),
            max_intent_total=max((i["total"] for i in stats["intents"]), default=1),
        )


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Endpoint tidak ditemukan."), 404
        engine = app.extensions["catbot_engine"]
        return render_template("404.html", engine=engine, message=None), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify(error="Metode HTTP tidak diizinkan untuk endpoint ini."), 405

    @app.errorhandler(500)
    def server_error(_error):
        return jsonify(error="Terjadi kesalahan pada server."), 500


app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
