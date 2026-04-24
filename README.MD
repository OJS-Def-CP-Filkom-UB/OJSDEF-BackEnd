# OJSDef — OJS Integrated Security Scanner (Backend API)

**OJSDef** adalah sebuah sistem SaaS (Software as a Service) yang berfungsi sebagai platform audit keamanan dan pemindaian kerentanan pada instalasi **Open Journal Systems (OJS)**. Repositori ini khusus menampung sistem **Backend (API Gateway & Task Workers)**.

## 🌟 Fitur Utama

OJSDef melakukan pemindaian keamanan OJS melalui dua pendekatan:
1. **Internal Scanning (Defensive):** Menggunakan plugin PHP yang dipasang di OJS target untuk mengambil data dari dalam (konfigurasi, integrity checker, plugin audit).
2. **External Scanning (Offensive):** Memindai target dari luar secara pasif (HTTPS headers, public endpoints, SSL/TLS analysis, OJS fingerprinting) menggunakan worker bot.

## 🏗️ Tech Stack

- **Framework:** FastAPI (Python 3.11+)
- **Database:** PostgreSQL 16 (dengan Asyncpg + SQLAlchemy 2.0)
- **Task Queue & Cache:** Celery 5 + Redis 7
- **Object Storage:** MinIO (S3 Compatible) untuk menyimpan laporan PDF
- **Autentikasi:** JWT + Role-Based Access Control (RBAC)
- **Infrastruktur:** Docker & Docker Compose

## 🚀 Panduan Setup & Instalasi

Untuk panduan instalasi lokal, arsitektur backend lengkap, dan instruksi menjalankan via Docker Compose, silakan baca dokumentasi teknis di file:
👉 **[README-BACKEND.md](./README-BACKEND.md)**

## 📚 Dokumentasi Pendukung

- Spesifikasi lengkap SRS terdapat pada `docs/SRS_OJSDEF.md`
- Panduan pengembangan untuk agen/worker terdapat pada `AGENTS.MD`

---
*Dikembangkan oleh Kelompok 3 — Topik G2, bekerja sama dengan Seclab Indonesia.*
