# OJSDef Agent Guidelines & Worker Architecture

Dokumen ini ditujukan sebagai panduan kerja bagi **AI Coding Agents** yang ikut serta mengembangkan repositori ini, serta dokumentasi untuk mendefinisikan arsitektur "Bot/Worker Agents" yang ada pada backend OJSDef.

## 🤖 Panduan untuk AI Coding Agents

Saat menulis atau memodifikasi kode di repositori ini, perhatikan aturan-aturan berikut:

1. **Tech Stack & Frameworks:**
   - Gunakan **FastAPI** (`v0.110.0`) dengan pendekatan **asinkron** (`async def`).
   - Gunakan **Pydantic v2** untuk validasi skema.
   - Interaksi database **wajib** menggunakan **SQLAlchemy 2.0 async** (`asyncpg`). Jangan gunakan query synchronous.
   - Manfaatkan **Celery** untuk semua proses yang memakan waktu lama (seperti network requests ke server OJS, parsing HTML, atau generating PDF).

2. **Struktur Direktori (Layered Architecture):**
   - `app/api/v1/`: Berisi router FastAPI (Controllers). Hanya boleh menangani validasi request/response HTTP.
   - `app/services/`: Logika bisnis. Router harus memanggil fungsi di layer ini.
   - `app/schemas/`: Model Pydantic untuk request dan response.
   - `app/models/`: Model ORM SQLAlchemy (ERD mapping).
   - `app/worker/`: Task Celery. Pastikan task terikat ke antrean (queue) yang benar.

3. **Multi-Tenancy:**
   - Aplikasi menggunakan konsep multi-tenant dengan Row-Level Security (RLS) PostgreSQL.
   - Hindari membuat query logic yang membocorkan data antar tenant. Gunakan tenant ID context di layer koneksi DB (sesuai SRS).

---

## 🏭 Arsitektur Sistem Worker (Celery Agents)

Sistem OJSDef membagi beban komputasinya ke beberapa worker mandiri. Saat mengembangkan fitur baru untuk scanning atau scoring, pastikan masuk ke antrean (Queue) worker yang tepat:

### 1. Internal Bot Worker (`queue: internal_scan`)
- **Tugas:** Menerima dan memproses callback payload (HMAC signed) dari Plugin PHP yang diinstall di OJS target.
- **Modul:** Konfigurasi scanner, Plugin auditor, RBAC auditor, File integrity (hash checker).

### 2. External Bot Worker (`queue: external_scan`)
- **Tugas:** Menjalankan script Python (`requests`, `beautifulsoup4`) untuk memindai OJS secara pasif dari luar.
- **Aturan:** *Rate-limited* (maksimal 10 requests per detik ke setiap target). Jangan gunakan serangan destruktif.
- **Modul:** Fingerprinting OJS, endpoint discovery, SSL/TLS analysis, header analysis.

### 3. Risk Scoring Worker (`queue: scoring`)
- **Tugas:** Mengambil hasil dari *Internal* dan *External* scan, kemudian mengkalkulasikan skor risiko menggunakan metode **CVSS v3**.
- **Output:** Menyimpan metrik *Overall Security Score* dan men-generate laporan akhir berupa PDF (via WeasyPrint) lalu diupload ke MinIO.

### 4. Notify Worker (`queue: notifications`)
- **Tugas:** Menerima *trigger* apabila ditemukan kerentanan berlevel *Critical* atau tugas scan selesai.
- **Output:** Mengirimkan pesan melalui SMTP (Email) atau API Telegram.

---

## 🗄️ Database Design & Integrasi ORM

Proyek ini telah dikonfigurasi dengan dua entitas dasar: **Tenants** dan **Users**.

- **Lokasi DDL PostgreSQL:** `database/schema.sql` (Berisi DDL murni dan enumerasi untuk Postgres).
- **Lokasi Model ORM SQLAlchemy:** `app/models/tenant.py` dan `app/models/user.py`.

### Aturan Model Database untuk Agen:
1. Setiap tabel harus mewarisi dari kelas basis `Base` yang terletak di `app/models/base.py`.
2. Gunakan `sqlalchemy.dialects.postgresql.UUID` untuk seluruh kolom ID (sebagai primary key maupun foreign key).
3. Kolom `created_at` dan `updated_at` harus menggunakan `func.now()` untuk auto-timestamp, serta `onupdate=func.now()` untuk update.
4. Gunakan `Enum` yang didefinisikan dari standar library python `enum.Enum` untuk tipe kolom enumerasi, contoh: `TenantPlan` dan `UserRole`.
5. Semua koneksi dan query wajib bersifat asinkron via `AsyncSession` (disediakan di `app/db/session.py`). Lihat contoh pengimplementasiannya di `app/api/v1/endpoints/users.py`.
