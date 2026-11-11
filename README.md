# CatBot: chatbot perawatan dasar kucing

CatBot adalah chatbot **berbasis aturan (rule-based)** yang membantu pemilik kucing mendapat
informasi dasar tentang **makanan**, **kebersihan**, dan **perawatan** kucing sehari-hari.
Dibangun dengan **Python (Flask >= 3.0)** dan **SQLite**, tanpa layanan AI eksternal.

> CatBot adalah asisten informasi perawatan dasar, **bukan pengganti dokter hewan**. Untuk gejala
> penyakit, kondisi darurat, atau masalah kesehatan serius, pengguna selalu diarahkan ke dokter hewan.

## Fitur

- 14 intent (salam, makanan, jadwal makan, minum, kebersihan, mandi, perawatan bulu, litter box,
  kesehatan, darurat, anak kucing, perilaku, penutup, fallback) dari `themes/catbot.json`.
- Mesin pencocokan intent: normalisasi teks, token overlap berbobot IDF, kemiripan
  `difflib.SequenceMatcher`, toleransi salah ketik ringan, dan ambang batas fallback.
- **Jalur darurat**: kata kunci seperti "keracunan", "kejang", atau "sulit bernapas" langsung
  diarahkan ke intent `darurat_kesehatan`.
- Pemilihan respons yang relevan: pertanyaan tentang kuku mendapat jawaban tentang kuku,
  bukan jawaban acak dari intent yang sama.
- Antarmuka web: landing page, chat interaktif dengan quick replies dan indikator mengetik.
- Dashboard admin: riwayat percakapan, tingkat dikenali, distribusi intent, daftar pertanyaan
  fallback, dan akurasi evaluasi dari CSV.
- Antarmuka terminal (`cli.py`) dan skrip evaluasi (`evaluate.py`).

## Struktur proyek

```text
catbot-flask/
├── app.py                # Flask: halaman web, API JSON, dashboard admin
├── cli.py                # Chatbot di terminal
├── evaluate.py           # Evaluasi akurasi intent dari CSV
├── requirements.txt
├── pytest.ini
├── chatbot/
│   ├── engine.py         # Mesin pencocokan intent
│   └── database.py       # Log percakapan & statistik (SQLite)
├── themes/catbot.json    # Basis pengetahuan (14 intent)
├── evaluasi/catbot.csv   # Dataset uji (pertanyaan, expected_intent)
├── templates/            # base, index, chat, admin, 404
├── static/css/style.css
├── static/js/chat.js
└── tests/                # test_engine.py, test_app.py
```

## Menjalankan aplikasi

Membutuhkan Python 3.10 atau lebih baru.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Buka <http://127.0.0.1:5000>. Database SQLite dibuat otomatis di `instance/catbot.db`.

### Variabel lingkungan

| Variabel | Fungsi | Default |
|---|---|---|
| `CATBOT_DB` | Lokasi file SQLite | `instance/catbot.db` |
| `CATBOT_ADMIN_TOKEN` | Token untuk membuka `/admin` | kosong (admin terbuka) |
| `CATBOT_SECRET_KEY` | Secret key Flask | nilai pengembangan |
| `HOST`, `PORT` | Alamat server pengembangan | `127.0.0.1`, `5000` |
| `FLASK_DEBUG` | `1` untuk mode debug | `0` |

**Untuk produksi:** atur `CATBOT_ADMIN_TOKEN` dan `CATBOT_SECRET_KEY`, lalu jalankan dengan
server WSGI, misalnya:

```bash
pip install gunicorn
CATBOT_ADMIN_TOKEN=token-rahasia gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

Dashboard dibuka dengan `/admin?token=token-rahasia` atau header `X-Admin-Token`.
Pakai HTTPS di depan aplikasi agar token tidak terkirim sebagai teks biasa.

## Halaman dan endpoint

| Method | Path | Keterangan |
|---|---|---|
| GET | `/` | Landing page, cakupan topik, dan disclaimer medis |
| GET | `/chat` | Antarmuka chat |
| POST | `/api/chat` | Kirim pesan, terima jawaban |
| GET | `/api/intents` | Ringkasan intent dan quick replies |
| GET | `/admin` | Dashboard admin |
| GET | `/health` | Cek status |

Contoh API:

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Berapa kali kucing makan dalam sehari?"}'
```

```json
{
  "reply": "Kucing dewasa umumnya diberi makan 2-3 kali sehari dengan porsi terukur. ...",
  "intent": "jadwal_makan",
  "score": 1.0,
  "is_fallback": false,
  "session_id": "3f2a..."
}
```

Pesan wajib berupa teks tidak kosong, maksimal 500 karakter. Pelanggaran dibalas HTTP 400
dengan field `error`.

## Terminal (CLI)

```bash
python cli.py            # percakapan biasa
python cli.py --debug    # tampilkan intent, skor, dan pola yang cocok
python cli.py --log      # simpan percakapan ke SQLite
```

Ketik `keluar` untuk mengakhiri.

## Evaluasi akurasi

```bash
python evaluate.py                 # tampilkan baris yang salah + akurasi per intent
python evaluate.py --verbose       # tampilkan semua baris
python evaluate.py --min-accuracy 0.95
```

Dataset ada di `evaluasi/catbot.csv` dengan kolom `pertanyaan` dan `expected_intent`
(termasuk baris `fallback` untuk pertanyaan di luar cakupan). Skrip berstatus keluar 1 jika
akurasi di bawah `--min-accuracy`, sehingga cocok dipakai di CI.

## Pengujian

```bash
pytest
```

`tests/test_engine.py` menguji basis pengetahuan, normalisasi, pencocokan, jalur darurat,
fallback, pemilihan respons, dan akurasi CSV. `tests/test_app.py` menguji halaman, endpoint API,
validasi input, pencatatan SQLite, dan dashboard admin.

## Menambah pengetahuan baru

Semua pengetahuan ada di `themes/catbot.json`. Untuk intent baru atau pola baru:

1. Tambahkan objek intent dengan `tag`, `patterns`, dan `responses`.
2. Atur `response_mode`: `random` (respons dipilih acak) atau `relevant` (respons dipilih
   berdasarkan kata kunci).
3. Untuk `relevant`, isi `response_keywords`: daftar kata kunci per respons, dengan urutan
   dan jumlah yang sama seperti `responses`. Jika tidak ada kata kunci yang cocok, respons pertama dipakai.
4. Tambahkan baris uji ke `evaluasi/catbot.csv`, lalu jalankan `python evaluate.py`.
5. Pantau tab **Pertanyaan fallback** di `/admin` untuk melihat apa yang sering ditanyakan
   pengguna tetapi belum dikenali.

Parameter penting di JSON: `threshold` (ambang skor minimum, default 0.5; naikkan agar lebih
ketat, turunkan agar lebih longgar) dan `urgent_keywords` (kata kunci jalur darurat).

## Cara kerja pencocokan

1. Teks dinormalisasi (huruf kecil, tanda baca dibuang) lalu di-token dan di-stem ringan.
2. Jika memuat kata kunci darurat, intent `darurat_kesehatan` langsung dipilih.
3. Setiap pola dinilai: `0.7 x token overlap berbobot IDF + 0.3 x kemiripan karakter`.
   Kata yang muncul di banyak intent (misalnya "kucing") tidak cukup untuk mencocokkan
   intent sendirian.
4. Intent dengan skor tertinggi dipilih jika skornya mencapai ambang batas, jika tidak
   dipakai intent `fallback`.

## Keterbatasan

- Pencocokan bersifat leksikal, jadi pertanyaan yang sangat berbeda dari pola yang ada bisa
  jatuh ke fallback. Perluas `patterns` untuk meningkatkan cakupan.
- CatBot tidak menyimpan konteks antar pesan; setiap pertanyaan diproses mandiri.
- Informasi bersifat umum dan tidak menggantikan pemeriksaan dokter hewan.
