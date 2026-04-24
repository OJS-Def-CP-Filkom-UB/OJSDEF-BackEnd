# OJSDef Backend Architecture & Setup

Backend ini telah dikonfigurasi berdasarkan **SRS OJSDef** dengan pendekatan _Layered Architecture_ dan skalabilitas tinggi menggunakan worker asinkron.

## 🗂️ Struktur Direktori

```text
OJSDEF-BackEnd/
├── app/
│   ├── api/
│   │   └── v1/          # Endpoints API (Routers)
│   ├── core/            # Konfigurasi aplikasi (Pydantic Settings, Security, JWT)
│   ├── db/              # Session DB (SQLAlchemy async) & Migrations (Alembic)
│   ├── models/          # Model SQLAlchemy (ERD OJSDef)
│   ├── schemas/         # Skema Pydantic (Request/Response Validation)
│   ├── services/        # Business logic (Scoring, Fingerprinting, Report Gen)
│   └── worker/          # Konfigurasi Celery & task modules
├── .env.example         # Template environment variables
├── docker-compose.yml   # Orkestrasi container (DB, Redis, MinIO, API, Workers)
├── Dockerfile           # Konfigurasi Docker image API & Workers (Python 3.11)
├── requirements.txt     # Dependencies aplikasi sesuai SRS
└── app/main.py          # Entrypoint aplikasi FastAPI
```

## 🚀 Fitur Utama Setup

1.  **FastAPI (Async):** Kinerja optimal menggunakan `asyncpg` untuk PostgreSQL.
2.  **Celery Workers Terpisah:** 
    *   `celery_internal` (Queue: `internal_scan`)
    *   `celery_external` (Queue: `external_scan`)
    *   `celery_scoring` (Queue: `scoring`)
    *   `celery_beat` (Untuk penjadwalan/Cron)
3.  **Infrastruktur Mandiri:** `docker-compose` sudah mencakup PostgreSQL 16, Redis 7 (broker & cache), dan MinIO (Object Storage PDF).
4.  **WeasyPrint Ready:** Dockerfile sudah menyertakan dependencies (Pango, Harfbuzz, cairo) agar WeasyPrint berjalan mulus untuk pembuatan laporan PDF.

## 🛠️ Cara Menjalankan

### Menggunakan Docker Compose (Direkomendasikan)
Gunakan ini untuk langsung menyalakan database, Redis, MinIO, Celery Workers, dan API.

```bash
# 1. Salin konfigurasi environment
cp .env.example .env

# 2. Build dan jalankan seluruh container
docker compose up --build -d
```
Cek `http://localhost:8000/docs` untuk melihat Swagger UI otomatis.

### Menjalankan API Secara Lokal (Development)
Jika ingin mengembangkan API tanpa menjalankan container API (hanya infra database/redis):

```bash
# 1. Jalankan infrastructure dependencies
docker compose up db redis minio -d

# 2. Buat virtual environment & install deps (jika belum)
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt

# 3. Jalankan server FastAPI
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 🗄️ Inisialisasi Database (Alembic)
Karena framework menggunakan SQLAlchemy 2.0 Async, saat pertama kali setup, inisiasi Alembic async:

```bash
alembic init -t async migrations
```
Setelah itu, ubah `migrations/env.py` agar mengimport models dan `settings.SQLALCHEMY_DATABASE_URI`.
