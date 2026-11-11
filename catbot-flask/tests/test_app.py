"""Integration test route web dan endpoint API CatBot."""

import pytest

from app import create_app
from chatbot import database as db


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "ADMIN_TOKEN": ""})


@pytest.fixture()
def client(app):
    return app.test_client()


def post_chat(client, payload):
    return client.post("/api/chat", json=payload)


# ------------------------------------------------------------------- halaman
def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "CatBot" in html
    assert "bukan pengganti dokter hewan" in html


def test_chat_page_has_quick_replies(client):
    response = client.get("/chat")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="chat-form"' in html
    assert "chat.js" in html
    assert html.count('class="chip"') >= 6


def test_static_assets_are_served(client):
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/chat.js").status_code == 200


def test_health_and_intents(client):
    assert client.get("/health").get_json()["status"] == "ok"
    data = client.get("/api/intents").get_json()
    assert len(data["intents"]) == 14
    assert data["quick_replies"]


def test_404_page_and_api_404(client):
    page = client.get("/tidak-ada")
    assert page.status_code == 404
    assert "tidak ditemukan" in page.get_data(as_text=True)
    api = client.get("/api/tidak-ada")
    assert api.status_code == 404
    assert "error" in api.get_json()


# ----------------------------------------------------------------- /api/chat
def test_api_chat_returns_reply(client):
    response = post_chat(client, {"message": "Berapa kali kucing makan dalam sehari?"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["intent"] == "jadwal_makan"
    assert data["is_fallback"] is False
    assert "2-3 kali sehari" in data["reply"]
    assert data["session_id"]


def test_api_chat_fallback(client):
    data = post_chat(client, {"message": "Siapa presiden Indonesia?"}).get_json()
    assert data["intent"] == "fallback"
    assert data["is_fallback"] is True


def test_api_chat_emergency(client):
    data = post_chat(client, {"message": "Kucing saya keracunan"}).get_json()
    assert data["intent"] == "darurat_kesehatan"
    assert "dokter hewan" in data["reply"]


def test_api_chat_keeps_valid_session_id(client):
    data = post_chat(client, {"message": "Hai", "session_id": "sesi-abc_123"}).get_json()
    assert data["session_id"] == "sesi-abc_123"


def test_api_chat_replaces_invalid_session_id(client):
    data = post_chat(client, {"message": "Hai", "session_id": "../../etc/passwd"}).get_json()
    assert data["session_id"] != "../../etc/passwd"
    assert len(data["session_id"]) == 32


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": ""}, {"message": "   "}, {"message": 123}, {"message": None}, ["bukan", "object"]],
)
def test_api_chat_rejects_invalid_payload(client, payload):
    response = post_chat(client, payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_api_chat_rejects_non_json_body(client):
    response = client.post("/api/chat", data="halo", content_type="text/plain")
    assert response.status_code == 400


def test_api_chat_rejects_too_long_message(client):
    response = post_chat(client, {"message": "a" * 501})
    assert response.status_code == 400


def test_api_chat_get_not_allowed(client):
    assert client.get("/api/chat").status_code == 405


def test_api_chat_unicode_roundtrip(client):
    data = post_chat(client, {"message": "Kucing boleh makan nasi? 🐱"}).get_json()
    assert data["intent"] == "makanan_kucing"


# ------------------------------------------------------------------ database
def test_conversations_are_logged(app, client):
    post_chat(client, {"message": "Hai", "session_id": "s1"})
    post_chat(client, {"message": "Siapa presiden Indonesia?", "session_id": "s1"})
    rows = db.get_recent_conversations(app.config["DATABASE"])
    assert len(rows) == 2
    assert rows[0]["user_message"] == "Siapa presiden Indonesia?"
    assert rows[0]["is_fallback"] == 1
    stats = db.get_stats(app.config["DATABASE"])
    assert stats["total"] == 2
    assert stats["fallback_count"] == 1
    assert stats["recognition_rate"] == 50.0
    assert stats["sessions"] == 1


def test_fallback_questions_are_grouped(app, client):
    for text in ["Cuaca hari ini?", "cuaca hari ini?", "Harga emas?"]:
        post_chat(client, {"message": text})
    questions = db.get_fallback_questions(app.config["DATABASE"])
    assert questions[0]["total"] == 2


def test_clear_conversations(app, client):
    post_chat(client, {"message": "Hai"})
    db.clear_conversations(app.config["DATABASE"])
    assert db.get_stats(app.config["DATABASE"])["total"] == 0


# --------------------------------------------------------------------- admin
def test_admin_dashboard_empty(client):
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Dashboard admin" in html
    assert "Belum ada percakapan" in html


def test_admin_dashboard_shows_data(client):
    post_chat(client, {"message": "Kucing saya makan coklat"})
    post_chat(client, {"message": "Siapa presiden Indonesia?"})
    html = client.get("/admin").get_data(as_text=True)
    assert "darurat_kesehatan" in html
    assert "Siapa presiden Indonesia?" in html
    assert "Akurasi evaluasi CSV" in html


def test_admin_escapes_html_in_messages(client):
    post_chat(client, {"message": "<script>alert(1)</script>"})
    html = client.get("/admin").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_admin_requires_token_when_configured(tmp_path):
    app = create_app(
        {"TESTING": True, "DATABASE": str(tmp_path / "t.db"), "ADMIN_TOKEN": "rahasia"}
    )
    client = app.test_client()
    assert client.get("/admin").status_code == 404
    assert client.get("/admin?token=salah").status_code == 404
    assert client.get("/admin?token=rahasia").status_code == 200
    assert client.get("/admin", headers={"X-Admin-Token": "rahasia"}).status_code == 200
