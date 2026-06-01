# Panduan Deployment OJSDef Backend ke VPS

> Dokumen ini mencakup spesifikasi VPS, setup lengkap dari nol, deployment via Docker Compose, integrasi domain Cloudflare, dan prosedur debugging/update.

---

## Daftar Isi

1. [Spesifikasi VPS](#1-spesifikasi-vps)
2. [Persiapan VPS (Ubuntu 22.04)](#2-persiapan-vps-ubuntu-2204)
3. [Instalasi Dependensi](#3-instalasi-dependensi)
4. [Clone dan Konfigurasi Proyek](#4-clone-dan-konfigurasi-proyek)
5. [Konfigurasi Environment Variables](#5-konfigurasi-environment-variables)
6. [Konfigurasi Nginx](#6-konfigurasi-nginx)
7. [Deploy dengan Docker Compose](#7-deploy-dengan-docker-compose)
8. [Migrasi Database dan Seed Data](#8-migrasi-database-dan-seed-data)
9. [Integrasi Domain Cloudflare](#9-integrasi-domain-cloudflare)
10. [SSL Manual — Tanpa Cloudflare Proxy (Opsional)](#10-ssl-manual--tanpa-cloudflare-proxy-opsional)
11. [Monitoring dan Maintenance](#11-monitoring-dan-maintenance)
12. [Prosedur Update Aplikasi](#12-prosedur-update-aplikasi)
13. [Debugging dan Troubleshooting](#13-debugging-dan-troubleshooting)

---

## 1. Spesifikasi VPS

### 1.1 Minimum (Development / Staging)

> Cukup untuk testing dan demo dengan beban ringan (≤5 target aktif, ≤10 scan/hari).

| Komponen | Minimum |
|----------|---------|
| CPU | 2 vCPU |
| RAM | 4 GB |
| Storage | 40 GB SSD |
| OS | Ubuntu 22.04 LTS |
| Bandwidth | 100 Mbps unmetered |

**Catatan minimum:**
- External scan worker dibatasi concurrency=1 agar tidak OOM
- WeasyPrint (PDF) butuh ~500 MB RAM saat render, jadi 4 GB bisa mepet saat bersamaan dengan scan

### 1.2 Rekomendasi (Production)

> Untuk produksi dengan ≤50 target OJS aktif dan beban scan rutin.

| Komponen | Rekomendasi |
|----------|-------------|
| CPU | 4 vCPU |
| RAM | 8 GB |
| Storage | 80 GB SSD (NVMe) |
| OS | Ubuntu 22.04 LTS |
| Bandwidth | 200 Mbps unmetered |

### 1.3 Skala Besar (≥100 Target)

| Komponen | Spesifikasi |
|----------|-------------|
| CPU | 8 vCPU |
| RAM | 16 GB |
| Storage | 200 GB SSD + volume terpisah untuk MinIO |
| OS | Ubuntu 22.04 LTS |
| Bandwidth | 1 Gbps |

**Pertimbangan penyedia VPS:**
- **Hetzner** (Jerman/Finland) — harga terbaik, cocok untuk proyek akademik
- **DigitalOcean** — dokumentasi lengkap, mudah setup
- **Vultr** — ada region Singapura (latensi rendah dari Indonesia)
- **Biznet Gio / IDCloudHost** — jika butuh data residency Indonesia

---

## 2. Persiapan VPS (Ubuntu 22.04)

### 2.1 Login Pertama dan Update Sistem

```bash
# Login sebagai root (ganti IP dengan IP VPS kamu)
ssh root@<IP_VPS>

# Update package list dan upgrade sistem
apt update && apt upgrade -y

# Reboot jika ada kernel update
reboot
```

### 2.2 Buat User Non-Root

Jangan jalankan aplikasi sebagai root.

```bash
# Buat user baru
adduser ojsdef

# Tambahkan ke grup sudo
usermod -aG sudo ojsdef

# Switch ke user baru
su - ojsdef
```

### 2.3 Setup SSH Key (Opsional tapi Direkomendasikan)

```bash
# Di mesin lokal kamu, buat SSH key jika belum ada
ssh-keygen -t ed25519 -C "ojsdef-vps"

# Copy public key ke VPS
ssh-copy-id ojsdef@<IP_VPS>

# Setelah berhasil login dengan key, nonaktifkan password auth (opsional)
sudo nano /etc/ssh/sshd_config
# Ubah: PasswordAuthentication no
sudo systemctl restart sshd
```

### 2.4 Konfigurasi Firewall (UFW)

```bash
# Enable UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Izinkan SSH (WAJIB sebelum enable!)
sudo ufw allow 22/tcp

# Izinkan HTTP dan HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Aktifkan firewall
sudo ufw enable

# Cek status
sudo ufw status verbose
```

> **Penting:** Port 8000 (FastAPI), 5432 (PostgreSQL), 6379 (Redis), 9000 (MinIO) TIDAK perlu dibuka ke publik karena semua traffic lewat Nginx di dalam Docker network.

### 2.5 Set Timezone

```bash
sudo timedatectl set-timezone Asia/Jakarta
timedatectl status
```

---

## 3. Instalasi Dependensi

### 3.1 Instalasi Docker

```bash
# Install dependensi Docker
sudo apt install -y ca-certificates curl gnupg lsb-release

# Tambahkan Docker GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Tambahkan repository Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Tambahkan user ke grup docker
sudo usermod -aG docker $USER

# Aktifkan Docker saat boot
sudo systemctl enable docker

# Logout dan login ulang agar grup docker aktif
exit
ssh ojsdef@<IP_VPS>

# Verifikasi
docker --version
docker compose version
```

### 3.2 Instalasi Git

```bash
sudo apt install -y git
```

### 3.3 Instalasi Certbot (untuk SSL Let's Encrypt)

```bash
sudo apt install -y certbot
```

---

## 4. Clone dan Konfigurasi Proyek

### 4.1 Clone Repositori

```bash
# Buat direktori proyek
sudo mkdir -p /opt/ojsdef
sudo chown $USER:$USER /opt/ojsdef
cd /opt/ojsdef

# Clone backend
git clone <URL_REPO_BACKEND> backend
cd backend
```

### 4.2 Struktur Direktori Setelah Clone

```
/opt/ojsdef/
└── backend/
    ├── app/
    ├── migrations/
    ├── nginx/
    │   └── nginx.conf
    ├── scripts/
    ├── app/templates/
    ├── docker-compose.yml
    ├── Dockerfile
    ├── .env.example
    ├── alembic.ini
    └── requirements.txt
```

---

## 5. Konfigurasi Environment Variables

### 5.1 Buat File .env

```bash
cd /opt/ojsdef/backend
cp .env.example .env
nano .env
```

### 5.2 Isi Setiap Variable

```env
# ─── Database ───────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://ojsdef:GANTI_PASS_KUAT@postgres:5432/ojsdef

# ─── Redis ──────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ─── JWT ────────────────────────────────────────────────────
# Generate: openssl rand -hex 32
JWT_SECRET=GANTI_DENGAN_SECRET_32_KARAKTER_MINIMAL
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30

# ─── Plugin Auth ────────────────────────────────────────────
# Generate: openssl rand -hex 32
PLUGIN_HMAC_SECRET=GANTI_PLUGIN_HMAC_SECRET_32CHARS
# Harus 32 karakter PERSIS (untuk AES-256)
PLUGIN_API_KEY_SECRET=0123456789abcdef0123456789abcdef

# ─── MinIO ──────────────────────────────────────────────────
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=GANTI_MINIO_ACCESS_KEY
MINIO_SECRET_KEY=GANTI_MINIO_SECRET_KEY
MINIO_BUCKET=ojsdef-reports
MINIO_USE_SSL=false

# ─── Email ──────────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@domainmu.com
SMTP_PASS=app_password_gmail
SMTP_FROM=noreply@domainmu.com

# ─── Telegram (opsional) ────────────────────────────────────
TELEGRAM_BOT_TOKEN=

# ─── NVD CVE API ────────────────────────────────────────────
# Daftar di: https://nvd.nist.gov/developers/request-an-api-key
CVE_API_KEY=

# ─── Sentry (opsional) ──────────────────────────────────────
SENTRY_DSN=

# ─── Aplikasi ───────────────────────────────────────────────
ENVIRONMENT=production
ALLOWED_ORIGINS=https://app.domainmu.com

# ─── Seed Admin ─────────────────────────────────────────────
SEED_ADMIN_EMAIL=admin@domainmu.com
SEED_ADMIN_PASSWORD=GANTI_PASSWORD_ADMIN_KUAT!

# ─── Flower Monitoring ──────────────────────────────────────
FLOWER_BASIC_AUTH=admin:GANTI_FLOWER_PASSWORD
```

### 5.3 Generate Secret yang Aman

```bash
# JWT_SECRET dan PLUGIN_HMAC_SECRET
openssl rand -hex 32

# PLUGIN_API_KEY_SECRET (harus tepat 32 karakter)
openssl rand -hex 32 | head -c 32
```

### 5.4 Amankan File .env

```bash
chmod 600 .env
```

---

## 6. Konfigurasi Nginx

```bash
mkdir -p /opt/ojsdef/backend/nginx
nano /opt/ojsdef/backend/nginx/nginx.conf
```

Ada **dua opsi** konfigurasi Nginx tergantung setup SSL yang dipilih. Jika menggunakan Cloudflare proxy, pilih **Opsi A**.

Ganti `api.domainmu.com` dan `flower.domainmu.com` dengan subdomain kamu di kedua opsi.

---

### Opsi A: Cloudflare Proxy — HTTP ke VPS (Direkomendasikan)

> Cloudflare yang handle SSL. Nginx di VPS cukup HTTP port 80. Tidak perlu certbot sama sekali.

```nginx
events {
    worker_connections 1024;
}

http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
    limit_req_zone $binary_remote_addr zone=plugin:10m rate=60r/m;

    server_tokens off;
    client_max_body_size 10M;

    # IP ranges Cloudflare — agar log mencatat IP asli visitor, bukan IP Cloudflare
    set_real_ip_from 103.21.244.0/22;
    set_real_ip_from 103.22.200.0/22;
    set_real_ip_from 103.31.4.0/22;
    set_real_ip_from 104.16.0.0/13;
    set_real_ip_from 104.24.0.0/14;
    set_real_ip_from 108.162.192.0/18;
    set_real_ip_from 131.0.72.0/22;
    set_real_ip_from 141.101.64.0/18;
    set_real_ip_from 162.158.0.0/15;
    set_real_ip_from 172.64.0.0/13;
    set_real_ip_from 173.245.48.0/20;
    set_real_ip_from 188.114.96.0/20;
    set_real_ip_from 190.93.240.0/20;
    set_real_ip_from 197.234.240.0/22;
    set_real_ip_from 198.41.128.0/17;
    real_ip_header CF-Connecting-IP;

    upstream fastapi_backend { server fastapi:8000; }
    upstream flower_monitor  { server flower:5555;  }

    # API Backend
    server {
        listen 80;
        server_name api.domainmu.com;

        location /plugin/v1/ {
            limit_req zone=plugin burst=20 nodelay;
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
            proxy_read_timeout 60s;
        }

        location /api/ {
            limit_req zone=api burst=10 nodelay;
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
            proxy_read_timeout 120s;
        }

        location /health {
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
        }

        location ~ ^/(docs|redoc|openapi.json) {
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
        }
    }

    # Flower Monitoring
    server {
        listen 80;
        server_name flower.domainmu.com;

        location / {
            proxy_pass http://flower_monitor;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

> **Catatan `X-Forwarded-Proto`:** Cloudflare menambahkan header `X-Forwarded-Proto: https` ke setiap request. Header ini diteruskan ke FastAPI sehingga aplikasi tahu koneksi original HTTPS, meskipun VPS hanya menerima HTTP.

---

### Opsi B: Direct HTTPS ke VPS (Tanpa Cloudflare Proxy)

> Digunakan jika DNS di-set "DNS only" (abu-abu) atau tidak memakai Cloudflare proxy. Butuh sertifikat SSL di VPS — lihat Bagian 10.

```nginx
events {
    worker_connections 1024;
}

http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;
    limit_req_zone $binary_remote_addr zone=plugin:10m rate=60r/m;

    server_tokens off;
    client_max_body_size 10M;

    upstream fastapi_backend { server fastapi:8000; }
    upstream flower_monitor  { server flower:5555;  }

    # HTTP → HTTPS redirect
    server {
        listen 80;
        server_name api.domainmu.com flower.domainmu.com;

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # HTTPS — API Backend
    server {
        listen 443 ssl;
        server_name api.domainmu.com;

        ssl_certificate     /etc/letsencrypt/live/api.domainmu.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/api.domainmu.com/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;
        ssl_session_cache shared:SSL:10m;

        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
        add_header X-Frame-Options DENY always;
        add_header X-Content-Type-Options nosniff always;

        location /plugin/v1/ {
            limit_req zone=plugin burst=20 nodelay;
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 60s;
        }

        location /api/ {
            limit_req zone=api burst=10 nodelay;
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }

        location /health {
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
        }

        location ~ ^/(docs|redoc|openapi.json) {
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
        }
    }

    # HTTPS — Flower Monitoring
    server {
        listen 443 ssl;
        server_name flower.domainmu.com;

        ssl_certificate     /etc/letsencrypt/live/flower.domainmu.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/flower.domainmu.com/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;

        location / {
            proxy_pass http://flower_monitor;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

---

## 7. Deploy dengan Docker Compose

### 7.1 Update docker-compose.yml untuk HTTPS

Tambahkan port 443 dan volume SSL pada service `nginx` di `docker-compose.yml`:

```yaml
nginx:
  image: nginx:1.25-alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - /etc/letsencrypt:/etc/letsencrypt:ro
    - /var/www/certbot:/var/www/certbot:ro
  depends_on:
    - fastapi
    - flower
```

### 7.2 Build dan Jalankan

```bash
cd /opt/ojsdef/backend

# Build image
docker compose build

# Jalankan semua service
docker compose up -d

# Cek status
docker compose ps
```

Output yang diharapkan (semua `Up`):

```
NAME                        STATUS
backend-fastapi-1           Up
backend-worker-internal-1   Up
backend-worker-external-1   Up
backend-worker-scoring-1    Up
backend-worker-notify-1     Up
backend-flower-1            Up
backend-postgres-1          Up (healthy)
backend-redis-1             Up (healthy)
backend-minio-1             Up
backend-nginx-1             Up
```

### 7.3 Verifikasi Awal

```bash
# Test health check (via HTTP dulu, sebelum SSL dipasang)
curl http://<IP_VPS>/health

# Cek log FastAPI
docker compose logs fastapi --tail=50
```

---

## 8. Migrasi Database dan Seed Data

```bash
cd /opt/ojsdef/backend

# Jalankan semua migration (termasuk 003 untuk audit_logs)
docker compose exec fastapi alembic upgrade head

# Verifikasi tabel terbuat
docker compose exec postgres psql -U ojsdef -d ojsdef -c "\dt"

# Seed data awal (tenant default + saas_admin)
docker compose exec fastapi python scripts/seed.py
```

### Daftar Migration

| Versi | File | Perubahan |
|-------|------|-----------|
| 001 | `001_initial.py` | Schema awal semua tabel |
| 002 | `002_plugin_connection_fields.py` | `trigger_endpoint`, `probe_endpoint`, `connection_mode`, `pending_scan_job_id` di `ojs_targets` |
| 003 | `003_audit_log_user_email_nullable_tenant.py` | Kolom `user_email` di `audit_logs`; `tenant_id` jadi nullable; index pada `created_at`, `action`, `tenant_id` |

> **Upgrade dari versi sebelumnya:** `alembic upgrade head` aman dijalankan — migration 003 menambah kolom `user_email` (server default `'unknown'`) dan mengubah `tenant_id` nullable tanpa menghapus data existing.

---

## 9. Integrasi Domain Cloudflare

### 9.1 Gambaran Umum Arsitektur

Dengan Cloudflare proxy aktif, traffic mengalir seperti ini:

```
Visitor ──HTTPS──► Cloudflare Edge ──HTTP──► VPS Nginx (port 80) ──► FastAPI/Flower
```

Cloudflare bertindak sebagai SSL terminator sekaligus CDN + WAF. VPS tidak perlu sertifikat SSL sama sekali jika menggunakan mode Flexible.

### 9.2 Setup DNS Records

Di Cloudflare Dashboard → pilih domain → **DNS** → **Add record**.

Tambahkan record berikut (ganti `<IP_VPS>` dengan IP VPS kamu):

| Type | Name | Content | Proxy Status | Keterangan |
|------|------|---------|--------------|------------|
| A | `api` | `<IP_VPS>` | **Proxied** (orange) | Endpoint API backend |
| A | `flower` | `<IP_VPS>` | **Proxied** (orange) | Celery task monitor |

> **Langsung Proxied** — berbeda dengan panduan lama yang menyuruh DNS only dulu. Karena kita tidak pakai certbot, DNS langsung di-proxy dari awal tidak masalah.

**Verifikasi propagasi DNS:**

```bash
# Tunggu 1-5 menit, lalu cek
# Output akan menunjukkan IP Cloudflare (bukan IP VPS kamu) — ini normal
nslookup api.domainmu.com

# Atau cek via curl, pastikan merespons (meski belum ada konten)
curl -I http://api.domainmu.com/health
```

### 9.3 Pilih Mode SSL Cloudflare

Cloudflare Dashboard → **SSL/TLS** → **Overview**:

| Mode | Alur | Perlu SSL di VPS? | Rekomendasi |
|------|------|-------------------|-------------|
| **Flexible** | Browser→CF: HTTPS, CF→VPS: HTTP | Tidak | Paling mudah |
| **Full** | Browser→CF: HTTPS, CF→VPS: HTTPS | Ya (boleh self-signed) | - |
| **Full (Strict)** | Browser→CF: HTTPS, CF→VPS: HTTPS | Ya (cert valid) | Jika butuh E2E encryption |

**Untuk setup ini, pilih: Flexible**

> Dengan Flexible, Cloudflare connect ke VPS via HTTP port 80 — persis yang kita setup di Nginx Opsi A. Visitor tetap lihat HTTPS di browser.

### 9.4 Pengaturan SSL/TLS Tambahan

Masih di menu **SSL/TLS**:

| Tab | Setting | Nilai |
|-----|---------|-------|
| Overview | SSL/TLS encryption mode | **Flexible** |
| Edge Certificates | Always Use HTTPS | **On** |
| Edge Certificates | Minimum TLS Version | **TLS 1.2** |
| Edge Certificates | Opportunistic Encryption | **On** |

### 9.5 Setup Subdomain `flower.domainmu.com`

Flower (Celery monitor) sudah otomatis dapat HTTPS dari Cloudflare karena DNS record-nya juga Proxied. Namun Flower perlu proteksi akses karena menampilkan task queue secara lengkap.

**Proteksi Flower via Cloudflare Access (gratis untuk 1 aplikasi):**

1. Cloudflare Dashboard → **Zero Trust** → **Access** → **Applications** → **Add an application**
2. Pilih: **Self-hosted**
3. Application name: `Flower Monitor`
4. Application domain: `flower.domainmu.com`
5. Policy: tambahkan email yang boleh akses (email akun Cloudflare kamu)
6. Save

Dengan ini, siapapun yang buka `flower.domainmu.com` harus login via Cloudflare Access (one-time email OTP) sebelum bisa lihat Flower.

> Alternatif lebih simpel: biarkan Flower basic auth dari `.env` (`FLOWER_BASIC_AUTH`) yang sudah dikonfigurasi di `docker-compose.yml`. Cloudflare tidak memblokir basic auth.

### 9.6 Cache Rules untuk Plugin Callback

Pastikan endpoint plugin callback tidak di-cache Cloudflare.

Cloudflare Dashboard → **Caching** → **Cache Rules** → **Create rule**:

- Rule name: `Bypass cache for plugin callback`
- When: `Hostname equals api.domainmu.com AND URI Path starts with /plugin/v1`
- Then: **Bypass cache**

### 9.7 Pengaturan Security Cloudflare

Cloudflare Dashboard → **Security**:

| Setting | Nilai | Alasan |
|---------|-------|--------|
| Security Level | Medium | Block bot + suspicious traffic |
| Bot Fight Mode | On | Cegah scraping |
| Browser Integrity Check | On | Verifikasi browser legit |

Cloudflare Dashboard → **Speed** → **Optimization**:

| Setting | Nilai |
|---------|-------|
| Auto Minify | Off (semua) | API response bukan HTML statis |
| Brotli | On |

### 9.8 Firewall Rule Opsional — Blokir Akses Langsung ke VPS

Dengan Cloudflare proxy aktif, idealnya VPS hanya menerima traffic dari IP Cloudflare (bukan dari IP lain langsung). Ini mencegah bypass Cloudflare.

```bash
# Izinkan hanya IP Cloudflare di port 80
# (jalankan di VPS setelah UFW aktif)

for ip in \
  103.21.244.0/22 \
  103.22.200.0/22 \
  103.31.4.0/22 \
  104.16.0.0/13 \
  104.24.0.0/14 \
  108.162.192.0/18 \
  131.0.72.0/22 \
  141.101.64.0/18 \
  162.158.0.0/15 \
  172.64.0.0/13 \
  173.245.48.0/20 \
  188.114.96.0/20 \
  190.93.240.0/20 \
  197.234.240.0/22 \
  198.41.128.0/17; do
    sudo ufw allow from $ip to any port 80
done

# Blokir port 80 dari semua IP lain
sudo ufw delete allow 80/tcp
sudo ufw deny 80/tcp

# Cek status
sudo ufw status numbered
```

> **Opsional** — untuk capstone, cukup biarkan port 80 terbuka untuk semua. Rule ini berguna untuk production serius.

---

## 10. SSL Manual — Tanpa Cloudflare Proxy (Opsional)

> **Skip bagian ini jika menggunakan Cloudflare proxy (Opsi A di Bagian 6).** Cloudflare sudah handle SSL secara otomatis.
>
> Bagian ini hanya relevan jika menggunakan Nginx **Opsi B** (direct HTTPS ke VPS tanpa Cloudflare proxy), atau jika Cloudflare proxy tidak bisa digunakan.

### 10.1 Persyaratan

- DNS record sudah di-set ke **DNS only** (abu-abu, bukan orange) di Cloudflare
- DNS sudah propagasi dan menunjuk ke IP VPS (`nslookup api.domainmu.com` mengembalikan IP VPS)

### 10.2 Hentikan Nginx Sementara

```bash
docker compose stop nginx
```

### 10.3 Dapatkan Sertifikat Let's Encrypt

```bash
sudo certbot certonly --standalone \
  -d api.domainmu.com \
  -d flower.domainmu.com \
  --email admin@domainmu.com \
  --agree-tos \
  --non-interactive

# Verifikasi sertifikat dibuat
sudo ls /etc/letsencrypt/live/
```

### 10.4 Mount Sertifikat ke Nginx Container

Update service `nginx` di `docker-compose.yml`:

```yaml
nginx:
  image: nginx:1.25-alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - /etc/letsencrypt:/etc/letsencrypt:ro
    - /var/www/certbot:/var/www/certbot:ro
  depends_on:
    - fastapi
    - flower
```

### 10.5 Jalankan Ulang Nginx

```bash
docker compose up -d nginx
```

### 10.6 Verifikasi HTTPS

```bash
curl https://api.domainmu.com/health
# Expected: {"status":"ok"}
```

### 10.7 Auto-Renewal SSL

```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Tambahkan cron job (buka dengan: sudo crontab -e)
0 3 * * * certbot renew --quiet && docker compose -f /opt/ojsdef/backend/docker-compose.yml restart nginx
```

---

## 11. Monitoring dan Maintenance

### 11.1 Melihat Log

```bash
cd /opt/ojsdef/backend

# Log semua service
docker compose logs -f

# Log service spesifik
docker compose logs -f fastapi
docker compose logs -f worker-internal
docker compose logs -f worker-external
docker compose logs -f worker-scoring
docker compose logs -f worker-notify

# 100 baris terakhir dengan timestamp
docker compose logs --tail=100 -t fastapi
```

### 11.2 Flower — Celery Task Monitor

Akses di: `https://flower.domainmu.com`  
Login dengan kredensial `FLOWER_BASIC_AUTH` di `.env`.

### 11.3 Health Check

```bash
# FastAPI
curl https://api.domainmu.com/health

# PostgreSQL
docker compose exec postgres pg_isready -U ojsdef

# Redis
docker compose exec redis redis-cli ping
```

### 11.4 Pemantauan Resource

```bash
# CPU dan memory per container
docker stats

# Disk usage
df -h

# Disk usage Docker volumes
docker system df
```

### 11.5 Backup Database

```bash
mkdir -p /opt/ojsdef/backup

# Backup manual
docker compose exec -T postgres pg_dump -U ojsdef ojsdef > \
  /opt/ojsdef/backup/ojsdef_$(date +%Y%m%d_%H%M%S).sql

# Cron job backup harian jam 2 pagi + hapus backup >7 hari
# Tambahkan di: sudo crontab -e
0 2 * * * docker compose -f /opt/ojsdef/backend/docker-compose.yml exec -T postgres pg_dump -U ojsdef ojsdef > /opt/ojsdef/backup/ojsdef_$(date +\%Y\%m\%d).sql && find /opt/ojsdef/backup -name "*.sql" -mtime +7 -delete
```

---

## 12. Prosedur Update Aplikasi

### 12.1 Update Kode (Tanpa Schema Change)

```bash
cd /opt/ojsdef/backend

# Pull perubahan terbaru
git pull origin main

# Rebuild image (jika requirements.txt atau Dockerfile berubah)
docker compose build fastapi worker-internal worker-external worker-scoring worker-notify

# Restart service tanpa downtime
docker compose up -d --no-deps fastapi
docker compose up -d --no-deps worker-internal worker-external worker-scoring worker-notify

# Verifikasi
docker compose ps
curl https://api.domainmu.com/health
```

### 12.2 Update dengan Migrasi Database

```bash
cd /opt/ojsdef/backend

# 1. Backup database DULU
docker compose exec -T postgres pg_dump -U ojsdef ojsdef > \
  /opt/ojsdef/backup/pre_migration_$(date +%Y%m%d_%H%M%S).sql

# 2. Pull kode terbaru
git pull origin main

# 3. Rebuild image
docker compose build

# 4. Stop workers (cegah task baru masuk saat migrasi)
docker compose stop worker-internal worker-external worker-scoring worker-notify

# 5. Jalankan migrasi
docker compose run --rm fastapi alembic upgrade head

# 6. Start ulang semua service
docker compose up -d

# 7. Verifikasi
docker compose logs fastapi --tail=30
```

### 12.3 Rollback Jika Update Gagal

```bash
# Rollback satu versi migration
docker compose run --rm fastapi alembic downgrade -1

# Restore dari backup jika perlu
cat /opt/ojsdef/backup/pre_migration_TIMESTAMP.sql | \
  docker compose exec -T postgres psql -U ojsdef ojsdef

# Rollback kode ke commit sebelumnya
git log --oneline -10
git checkout <COMMIT_HASH>
docker compose build
docker compose up -d
```

---

## 13. Debugging dan Troubleshooting

### 13.1 Container Tidak Mau Start

```bash
# Lihat log container yang gagal
docker compose logs <nama-service>

# Cek exit code semua container
docker compose ps -a

# Masuk ke container untuk debug
docker compose run --rm fastapi bash
```

**Error umum:**

| Error | Penyebab | Solusi |
|-------|----------|--------|
| `could not connect to server: Connection refused` | PostgreSQL belum healthy | Tunggu: `docker compose ps postgres` sampai `(healthy)` |
| `ConnectionRefusedError: redis` | Redis belum ready | `docker compose restart redis` |
| `ModuleNotFoundError` | Image belum di-rebuild setelah requirements berubah | `docker compose build` |
| `FileNotFoundError: .env` | File .env belum dibuat | `cp .env.example .env && nano .env` |
| `sqlalchemy.exc.OperationalError` | DATABASE_URL salah atau postgres belum jalan | Cek `.env` dan `docker compose ps postgres` |

### 13.2 Error saat Alembic Migrate

```bash
# Lihat versi migration aktif
docker compose run --rm fastapi alembic current

# Lihat history
docker compose run --rm fastapi alembic history

# Preview SQL sebelum apply (tanpa eksekusi)
docker compose run --rm fastapi alembic upgrade head --sql

# Jika tabel sudah ada tapi alembic tidak tahu (migration conflict)
docker compose run --rm fastapi alembic stamp head
```

### 13.3 Celery Task Gagal / Tidak Jalan

```bash
# Cek panjang antrian di Redis
docker compose exec redis redis-cli llen internal_scan
docker compose exec redis redis-cli llen external_scan
docker compose exec redis redis-cli llen scoring
docker compose exec redis redis-cli llen notifications

# Inspect task yang sedang active
docker compose exec fastapi celery -A app.celery_app inspect active

# Restart worker yang bermasalah
docker compose restart worker-internal

# Purge antrian jika task stuck (HATI-HATI: menghapus semua task pending!)
docker compose exec fastapi celery -A app.celery_app purge -Q internal_scan
```

### 13.4 Scan Job Stuck di Status "running"

```bash
# Cek progress di Redis
docker compose exec redis redis-cli get scan_progress:<JOB_ID>

# Update status manual (ganti UUID)
docker compose exec postgres psql -U ojsdef -d ojsdef -c \
  "UPDATE scan_jobs SET status='failed', error_message='Timeout - job stuck' WHERE id='<JOB_UUID>';"
```

### 13.5 Error 502 Bad Gateway dari Nginx

```bash
# Cek FastAPI container
docker compose ps fastapi
docker compose logs fastapi --tail=50

# Test koneksi langsung ke FastAPI (bypass nginx, dari dalam Docker network)
docker compose exec nginx wget -qO- http://fastapi:8000/health

# Test konfigurasi nginx
docker compose exec nginx nginx -t

# Reload nginx tanpa restart
docker compose exec nginx nginx -s reload
```

### 13.6 MinIO / PDF Report Error

```bash
# Cek MinIO log
docker compose logs minio --tail=30

# Cek isi bucket via mc CLI
docker compose exec minio mc alias set local http://localhost:9000 \
  $MINIO_ACCESS_KEY $MINIO_SECRET_KEY
docker compose exec minio mc ls local/ojsdef-reports

# Buat bucket jika belum ada
docker compose exec minio mc mb local/ojsdef-reports
```

### 13.7 JWT / Auth Error

```bash
# Flush semua refresh token (force logout semua user)
docker compose exec redis redis-cli --scan --pattern "refresh:*" | \
  xargs docker compose exec redis redis-cli del

# Pastikan JWT_SECRET di .env tidak berubah setelah token diterbitkan
# Jika JWT_SECRET berubah, semua token lama langsung invalid
```

### 13.8 Debug Slow Query PostgreSQL

```bash
# Aktifkan log query lambat (>500ms)
docker compose exec postgres psql -U ojsdef -d ojsdef -c \
  "ALTER SYSTEM SET log_min_duration_statement = '500'; SELECT pg_reload_conf();"

# Lihat log PostgreSQL
docker compose logs postgres --tail=100

# Nonaktifkan setelah debug selesai
docker compose exec postgres psql -U ojsdef -d ojsdef -c \
  "ALTER SYSTEM SET log_min_duration_statement = '-1'; SELECT pg_reload_conf();"
```

### 13.9 Bersihkan Resource Docker (Disk Penuh)

```bash
# Hapus image, container, dan cache yang tidak terpakai
docker system prune -f

# Hapus volume yang tidak terpakai (HATI-HATI: pastikan bukan volume aktif)
docker volume prune -f

# Lihat volume aktif
docker volume ls
```

### 13.10 Reset Total (Last Resort)

> **PERINGATAN**: Semua data akan hilang. Lakukan backup dulu.

```bash
cd /opt/ojsdef/backend

# Backup terakhir
docker compose exec -T postgres pg_dump -U ojsdef ojsdef > \
  /opt/ojsdef/backup/emergency_$(date +%Y%m%d_%H%M%S).sql

# Hapus semua container, volume, dan image lokal
docker compose down -v --rmi local

# Build ulang dan deploy
docker compose build
docker compose up -d
docker compose run --rm fastapi alembic upgrade head
docker compose run --rm fastapi python scripts/seed.py
```

---

## Catatan Versi Terbaru

### Celery Beat (Periodic Tasks)

Aktifkan Celery beat scheduler agar `cleanup_stale_pending_jobs` berjalan setiap 5 menit (membersihkan scan job yang stuck di status `queued`/`running` lebih dari 30 menit):

```bash
# Tambahkan service ini ke docker-compose.yml:
celery-beat:
  build: .
  command: celery -A app.celery_app beat --loglevel=info
  env_file: .env
  depends_on:
    - redis
  restart: unless-stopped
```

Atau jalankan manual:
```bash
docker compose exec fastapi celery -A app.celery_app beat --loglevel=info
```

### UserRole yang Valid

Role yang dikenali sistem: `admin_ojs` | `saas_admin` | `viewer`. Role `it_admin` sudah dihapus.

---

## Checklist Deployment

Sebelum declare production-ready, pastikan semua item ini terpenuhi:

- [ ] `.env` terisi lengkap dengan secret yang kuat (bukan nilai dari `.env.example`)
- [ ] `chmod 600 .env` sudah dijalankan
- [ ] `docker compose ps` — semua container berstatus `Up` atau `Up (healthy)`
- [ ] `alembic upgrade head` berhasil, semua tabel terbuat
- [ ] `scripts/seed.py` berhasil, admin user bisa login
- [ ] `curl https://api.domainmu.com/health` mengembalikan `{"status":"ok"}`
- [ ] Cloudflare DNS record `api` dan `flower` berstatus **Proxied** (orange cloud)
- [ ] Cloudflare SSL/TLS mode: **Flexible** (atau Full jika pakai cert di VPS)
- [ ] Cloudflare **Always Use HTTPS**: On
- [ ] Cache Rule bypass untuk `/plugin/v1/*` sudah dibuat
- [ ] Firewall UFW hanya membuka port 22, 80, 443
- [ ] Cron job backup database aktif (`sudo crontab -l`)
- [ ] Flower dashboard accessible di `https://flower.domainmu.com`
- [ ] Test scan end-to-end berhasil (job sampai status "completed")
- [ ] Email notifikasi berfungsi
- [ ] Celery beat service berjalan (`docker compose ps celery-beat`)
- [ ] `alembic upgrade head` — migration 003 sudah dijalankan (cek kolom `user_email` di tabel `audit_logs`)
