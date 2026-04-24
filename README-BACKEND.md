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

---

## 👨‍💻 Backend Developer Guidelines

Berikut adalah panduan lengkap dan best practices bagi para developer backend saat mengerjakan fitur di repositori ini.

### 1. Prinsip Layered Architecture
Pisahkan antara _Routing_, _Business Logic_, dan _Data Access_ agar kode mudah di-_test_ dan *maintainable*.
- **`app/api/v1/endpoints/` (Controllers):** Hanya bertugas menerima *request*, memanggil fungsi validasi Pydantic, memanggil *service layer*, dan mengembalikan response HTTP. **Dilarang keras** menaruh _business logic_ atau query database rumit di layer ini.
- **`app/services/` (Business Logic):** Di sinilah inti dari algoritma aplikasi (seperti _Risk Scoring_, pemanggilan API eksternal, dll).
- **`app/models/` (Data Access):** Representasi tabel database. Relasi dan *constraint* ditulis di sini.
- **`app/schemas/` (Pydantic Validation):** Validasi ketat untuk payload *request* dan struktur *response*. Gunakan model yang berbeda untuk Request (`*Create`, `*Update`) dan Response (`*Response`).

### 2. Aturan Database & SQLAlchemy ORM
- **Selalu Gunakan Async:** Karena kita menggunakan `asyncpg`, pastikan semua interaksi database dilakukan di dalam fungsi `async def` dengan menggunakan `await db.execute(...)`.
- **Primary Key UUID:** Gunakan UUIDv4 (native Postgres `UUID`) untuk semua `id` utama guna menjaga keamanan (mencegah *ID enumeration*).
- **Timezone-aware:** Selalu gunakan `DateTime(timezone=True)` dan `func.now()` untuk mencatat *timestamp*.
- **Row-Level Security (RLS) & Tenancy:** OJSDef adalah platform *SaaS Multi-Tenant*. Semua query data operasional HARUS difilter berdasarkan `tenant_id`. Pastikan Anda selalu mem-passing `tenant_id` atau bergantung pada RLS Postgres.

### 3. Migrasi Database (Alembic)
Jangan pernah mengubah skema tabel secara manual di DBMS.
1. Ubah file di `app/models/`.
2. Generate migrasi baru: `alembic revision --autogenerate -m "Deskripsi perubahan"`
3. Periksa file hasil generate di `migrations/versions/`. Pastikan tidak ada DROP table yang tidak disengaja.
4. Terapkan perubahan: `alembic upgrade head`

### 4. Background Tasks & Celery
Jangan pernah memblokir HTTP *event loop* FastAPI dengan task berat (>500ms).
- Task pengiriman email, integrasi ke API NVD/CVE, *external scanning*, dan *PDF generation* wajib dimasukkan ke dalam antrean (Queue) Celery (`app/worker/tasks/`).
- Gunakan `@celery_app.task()` dan *enqueue* dengan `.delay()`.
- Pastikan task bersifat **Idempotent** (aman jika dieksekusi lebih dari satu kali bila terjadi _retry_ otomatis).

### 5. Error Handling & HTTP Status
- Gunakan `HTTPException` dari FastAPI dengan status code yang semantik.
  - `400 Bad Request`: Kesalahan input atau validasi logika gagal.
  - `401 Unauthorized`: Kredensial tidak valid atau *token expired*.
  - `403 Forbidden`: User tidak memiliki hak akses (RBAC error).
  - `404 Not Found`: Data tidak ada / dilindungi RLS dari user lain.
  - `422 Unprocessable Entity`: Input gagal tervalidasi oleh Pydantic (Otomatis ditangani FastAPI).
  - `500 Internal Server Error`: Kesalahan *unhandled exception*.

### 6. Git Workflow
- Gunakan *branching model*:
  - `main`: Branch produksi, kode harus stabil.
  - `develop`: Branch integrasi utama.
  - `feature/{nama-fitur}`: Untuk pengembangan fitur baru (contoh: `feature/cvss-scoring`).
  - `bugfix/{nama-bug}`: Untuk perbaikan bug.
- Lakukan *Pull Request (PR)* ke `develop` dan wajib *Code Review* sebelum di-_merge_.
- Jangan *commit* file rahasia (kredensial, `.env`, dsb). Pastikan sesuai `.gitignore`.
