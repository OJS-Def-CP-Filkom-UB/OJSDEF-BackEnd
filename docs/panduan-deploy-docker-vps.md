# Panduan Deployment OJSDef Backend ke VPS (Docker)

**Last Updated:** 2026-06-01

## Arsitektur Deployment

```
┌─ Browser ─────────────────────────────────────────────────────────┐
│                                                                    │
└─ Nginx (reverse proxy) :443                                       │
   ├─ Next.js Frontend :3000  (berbeda VPS/port)                  │
   └─ FastAPI Backend :8000                                        │
       ├─ PostgreSQL 16 :5432 (dalam docker)                       │
       ├─ Redis 7 :6379 (Celery broker + cache)                   │
       ├─ Celery Workers (4 queue types):                          │
       │  ├─ internal_scan (concurrency 4)                         │
       │  ├─ external_scan (concurrency 2)                         │
       │  ├─ scoring (concurrency 2)                               │
       │  └─ notifications (concurrency 4)                         │
       ├─ Celery Beat (periodic tasks, cleanup setiap 5 menit)   │
       └─ MinIO :9000 (PDF reports, S3-compatible)                │
```

## Prasyarat

- **VPS Ubuntu 22.04 LTS**, minimum:
  - 4 vCPU (atau bisa 2 vCPU + swap)
  - 8 GB RAM (minimum 4 GB, recommended 8+)
  - 40 GB SSD
  - Network: 1 Mbps upstream (untuk CVE updates)

- **Software**:
  - Docker CE >= 24.0
  - Docker Compose v2 >= 2.10
  - Git
  - nano atau vim (untuk edit config)

- **Domain/Subdomain**:
  - Contoh: `api.ojsdef.example.com` (untuk API Backend)
  - SSL/TLS certificate (Let's Encrypt atau paid)

## Setup VPS (First Time)

### 1. Update system dan install Docker

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git nano htop

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker
docker --version
docker compose version
```

### 2. Clone repository

```bash
cd /opt  # atau /home/username/apps — pilih sesuai preferensi
git clone https://github.com/username/OJSDEF-BackEnd.git
cd OJSDEF-BackEnd

# Gunakan branch stabil (misal main atau v1.0)
git checkout main
```

### 3. Setup environment variables

```bash
# Copy template env
cp .env.example .env

# Edit dengan nilai production
nano .env
```

**File `.env` harus berisi:**

```env
# Database
DATABASE_URL=postgresql+asyncpg://ojsdef:YOUR_SECURE_DB_PASSWORD@postgres:5432/ojsdef
REDIS_URL=redis://redis:6379/0

# JWT & Security
JWT_SECRET=YOUR_SECURE_32_CHAR_SECRET_KEY_HERE_MIN
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
PLUGIN_API_KEY_SECRET=0123456789abcdef0123456789abcdef

# MinIO (S3 object storage untuk PDF)
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=YOUR_MINIO_ACCESS_KEY
MINIO_SECRET_KEY=YOUR_MINIO_SECRET_KEY
MINIO_BUCKET=ojsdef-reports
MINIO_USE_SSL=false

# SMTP (Email notifications)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@ojsdef.com
SMTP_PASS=YOUR_APP_PASSWORD
SMTP_FROM=noreply@ojsdef.com

# CVE Database
CVE_API_KEY=YOUR_NVD_API_KEY

# Telegram (optional)
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_TOKEN

# Monitoring
SENTRY_DSN=YOUR_SENTRY_DSN

# Environment
ENVIRONMENT=production
ALLOWED_ORIGINS=https://dashboard.ojsdef.example.com

# Seed admin (CHANGE ASAP after first login)
SEED_ADMIN_EMAIL=admin@ojsdef.com
SEED_ADMIN_PASSWORD=YOUR_SECURE_ADMIN_PASSWORD

# Flower (Celery monitoring) basic auth
FLOWER_BASIC_AUTH=flower:YOUR_FLOWER_PASSWORD
```

### 4. Buat file `docker-compose.yml`

Salinan ke `/opt/OJSDEF-BackEnd/docker-compose.yml`:

```yaml
version: '3.9'

services:
  # PostgreSQL Database
  postgres:
    image: postgres:16-alpine
    container_name: ojsdef-postgres
    environment:
      POSTGRES_DB: ojsdef
      POSTGRES_USER: ojsdef
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-ojsdef_pass}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ojsdef"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - ojsdef-network
    restart: unless-stopped

  # Redis (Celery broker + cache)
  redis:
    image: redis:7-alpine
    container_name: ojsdef-redis
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - ojsdef-network
    restart: unless-stopped

  # MinIO (S3-compatible object storage)
  minio:
    image: minio/minio:latest
    container_name: ojsdef-minio
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-ojsdef_minio}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-ojsdef_minio_secret}
    volumes:
      - minio_data:/minio_data
    ports:
      - "9000:9000"
      - "9001:9001"
    command: server /minio_data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - ojsdef-network
    restart: unless-stopped

  # FastAPI Backend
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-api
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      JWT_ALGORITHM: ${JWT_ALGORITHM}
      PLUGIN_API_KEY_SECRET: ${PLUGIN_API_KEY_SECRET}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET: ${MINIO_BUCKET}
      MINIO_USE_SSL: ${MINIO_USE_SSL}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASS: ${SMTP_PASS}
      SMTP_FROM: ${SMTP_FROM}
      CVE_API_KEY: ${CVE_API_KEY}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      SENTRY_DSN: ${SENTRY_DSN}
      ENVIRONMENT: ${ENVIRONMENT}
      ALLOWED_ORIGINS: ${ALLOWED_ORIGINS}
      SEED_ADMIN_EMAIL: ${SEED_ADMIN_EMAIL}
      SEED_ADMIN_PASSWORD: ${SEED_ADMIN_PASSWORD}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy
    volumes:
      - ./app:/app/app
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000"

  # Celery Worker - Internal Scans
  celery-internal:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-celery-internal
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      PLUGIN_API_KEY_SECRET: ${PLUGIN_API_KEY_SECRET}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET: ${MINIO_BUCKET}
      MINIO_USE_SSL: ${MINIO_USE_SSL}
      CVE_API_KEY: ${CVE_API_KEY}
      ENVIRONMENT: ${ENVIRONMENT}
      SENTRY_DSN: ${SENTRY_DSN}
    depends_on:
      - postgres
      - redis
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: celery -A app.celery_app worker -Q internal_scan --concurrency=4 --loglevel=info

  # Celery Worker - External Scans
  celery-external:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-celery-external
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      CVE_API_KEY: ${CVE_API_KEY}
      ENVIRONMENT: ${ENVIRONMENT}
      SENTRY_DSN: ${SENTRY_DSN}
    depends_on:
      - postgres
      - redis
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: celery -A app.celery_app worker -Q external_scan --concurrency=2 --loglevel=info

  # Celery Worker - Scoring
  celery-scoring:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-celery-scoring
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET: ${MINIO_BUCKET}
      MINIO_USE_SSL: ${MINIO_USE_SSL}
      ENVIRONMENT: ${ENVIRONMENT}
      SENTRY_DSN: ${SENTRY_DSN}
    depends_on:
      - postgres
      - redis
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: celery -A app.celery_app worker -Q scoring --concurrency=2 --loglevel=info

  # Celery Worker - Notifications
  celery-notifications:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-celery-notifications
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASS: ${SMTP_PASS}
      SMTP_FROM: ${SMTP_FROM}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      ENVIRONMENT: ${ENVIRONMENT}
      SENTRY_DSN: ${SENTRY_DSN}
    depends_on:
      - postgres
      - redis
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: celery -A app.celery_app worker -Q notifications --concurrency=4 --loglevel=info

  # Celery Beat - Periodic Tasks
  celery-beat:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-celery-beat
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      ENVIRONMENT: ${ENVIRONMENT}
      SENTRY_DSN: ${SENTRY_DSN}
    depends_on:
      - postgres
      - redis
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: celery -A app.celery_app beat --loglevel=info

  # Flower - Celery Monitoring
  flower:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ojsdef-flower
    environment:
      CELERY_BROKER_URL: ${REDIS_URL}
      FLOWER_BASIC_AUTH: ${FLOWER_BASIC_AUTH:-flower:flower_pass}
    ports:
      - "5555:5555"
    depends_on:
      - redis
      - api
    networks:
      - ojsdef-network
    restart: unless-stopped
    command: celery -A app.celery_app flower --port=5555

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  minio_data:
    driver: local

networks:
  ojsdef-network:
    driver: bridge
```

### 5. Buat `Dockerfile` (di root project)

File `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 6. Setup Nginx Reverse Proxy

Buat file `/etc/nginx/sites-available/ojsdef-api`:

```nginx
upstream fastapi_backend {
    server api:8000;
}

upstream flower_monitor {
    server flower:5555;
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name api.ojsdef.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.ojsdef.example.com;

    # SSL certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/api.ojsdef.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.ojsdef.example.com/privkey.pem;

    # SSL config
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;

    # Logs
    access_log /var/log/nginx/ojsdef-api-access.log;
    error_log /var/log/nginx/ojsdef-api-error.log;

    # API proxy
    location / {
        proxy_pass http://fastapi_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
    }

    # Flower monitoring (opsional, bisa akses dari internal saja)
    location /flower/ {
        proxy_pass http://flower_monitor/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Basic auth (dari .env FLOWER_BASIC_AUTH)
        auth_basic "Flower Monitoring";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }
}
```

Enable Nginx site:

```bash
sudo ln -s /etc/nginx/sites-available/ojsdef-api /etc/nginx/sites-enabled/
sudo nginx -t  # test config
sudo systemctl reload nginx
```

### 7. Setup SSL dengan Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx

# Get certificate
sudo certbot certonly --nginx -d api.ojsdef.example.com

# Setup auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

## Deployment Langkah demi Langkah

### Step 1: Mulai services dasar

```bash
cd /opt/OJSDEF-BackEnd

# Start database, redis, minio
docker compose up -d postgres redis minio

# Tunggu services ready (cek logs)
sleep 15
docker compose logs postgres redis minio
```

### Step 2: Run database migrations

```bash
docker compose run --rm api alembic upgrade head
```

### Step 3: Start API & workers

```bash
# Jalankan semua services
docker compose up -d

# Verify status
docker compose ps
docker compose logs api | tail -50
```

### Step 4: Verifikasi services

```bash
# API health check
curl https://api.ojsdef.example.com/health

# Response: {"status":"ok"}

# Check workers
docker compose exec api celery -A app.celery_app inspect active_queues

# Check Flower (opsional)
# Akses: https://api.ojsdef.example.com/flower/ (dengan basic auth)
```

### Step 5: Cek semua logs

```bash
# API logs
docker compose logs api --tail=100 -f

# Celery logs
docker compose logs celery-internal --tail=50
docker compose logs celery-beat --tail=20
```

## Maintenance & Operations

### Update aplikasi (Pull latest)

```bash
cd /opt/OJSDEF-BackEnd

# Pull changes
git pull origin main

# Rebuild images (jika ada requirement baru)
docker compose build api celery-internal celery-external celery-scoring celery-notifications celery-beat

# Run migrations
docker compose run --rm api alembic upgrade head

# Restart services
docker compose up -d api celery-internal celery-external celery-scoring celery-notifications celery-beat
```

### Backup database

```bash
# Dump PostgreSQL
docker compose exec postgres pg_dump -U ojsdef ojsdef > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup MinIO data (jika penting)
tar czf minio_backup_$(date +%Y%m%d).tar.gz /var/lib/docker/volumes/ojsdef-backendminio_data/_data/
```

### Monitor services

```bash
# System resource usage
docker stats

# Service logs
docker compose logs -f --tail=100 api

# Database connections
docker compose exec postgres psql -U ojsdef ojsdef -c "SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;"

# Redis memory
docker compose exec redis redis-cli INFO memory

# Flower Celery monitoring
# Open: https://api.ojsdef.example.com/flower/
```

### Restart services

```bash
# Graceful restart
docker compose restart api celery-internal celery-external celery-scoring celery-notifications

# Full restart
docker compose down
docker compose up -d
```

### View real-time logs

```bash
# Follow API logs
docker compose logs -f api

# Follow specific worker
docker compose logs -f celery-internal

# Follow multiple
docker compose logs -f api celery-internal
```

## Troubleshooting

### Problem: API tidak bisa connect ke database

**Symptoms**: `docker compose logs api` → `sqlalchemy.exc.OperationalError`

**Solution**:
```bash
# Cek postgres health
docker compose exec postgres pg_isready -U ojsdef

# Verify credentials di .env
cat .env | grep DATABASE_URL

# Restart postgres
docker compose restart postgres
```

### Problem: Celery tasks tidak berjalan

**Symptoms**: Queue terlihat kosong di Flower

**Solution**:
```bash
# Cek Redis connection
docker compose exec redis redis-cli ping  # Should: PONG

# Cek Celery beat
docker compose logs celery-beat

# Restart beat + workers
docker compose restart celery-beat celery-internal celery-external celery-scoring celery-notifications
```

### Problem: MinIO not accessible

**Symptoms**: PDF generation fails, reports tidak tersimpan

**Solution**:
```bash
# Cek MinIO logs
docker compose logs minio

# Cek credentials
docker compose exec minio mc admin config get local

# Test S3 API
curl http://localhost:9000/health/live

# Restart MinIO
docker compose restart minio
```

### Problem: SSL certificate error

**Symptoms**: `curl: (60) SSL certificate problem`

**Solution**:
```bash
# Check certificate expiry
sudo certbot certificates

# Renew manually
sudo certbot renew --force-renewal

# Check Nginx SSL config
sudo nginx -t
sudo systemctl reload nginx
```

### Problem: Nginx 502 Bad Gateway

**Symptoms**: `api.ojsdef.example.com` returns 502

**Solution**:
```bash
# Check if API container is running
docker compose ps api

# Check API logs
docker compose logs api

# Check Nginx logs
sudo tail -f /var/log/nginx/ojsdef-api-error.log

# Verify API is responding
docker compose exec api curl http://localhost:8000/health
```

## Performance Tuning (Optional)

### Increase database connections
Edit `docker-compose.yml`, section `postgres`:
```yaml
environment:
  POSTGRES_INITDB_ARGS: "-c max_connections=200 -c shared_buffers=256MB"
```

### Increase worker concurrency
Edit `docker-compose.yml`, section `celery-*`:
```yaml
command: celery -A app.celery_app worker -Q internal_scan --concurrency=8 --loglevel=info
```

### Cache optimization (Redis)
```bash
docker compose exec redis redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

## Security Best Practices

1. **Change default passwords**:
   - `SEED_ADMIN_PASSWORD` → ganti setelah first login
   - `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` → gunakan secret manager
   - `JWT_SECRET` → min 32 char, random

2. **Firewall**:
   ```bash
   sudo ufw allow 22/tcp  # SSH
   sudo ufw allow 80/tcp  # HTTP
   sudo ufw allow 443/tcp # HTTPS
   sudo ufw allow 9000/tcp # MinIO (opsional, internal only)
   ```

3. **Database backup**:
   ```bash
   # Cron job (backup setiap hari pukul 2 AM)
   0 2 * * * docker compose -f /opt/OJSDEF-BackEnd/docker-compose.yml exec -T postgres pg_dump -U ojsdef ojsdef > /backups/ojsdef_$(date +\%Y\%m\%d).sql
   ```

4. **Log rotation**:
   ```bash
   sudo nano /etc/logrotate.d/ojsdef
   ```
   Content:
   ```
   /var/log/nginx/ojsdef-api-*.log {
       daily
       rotate 14
       compress
       missingok
       notifempty
   }
   ```

## Support & References

- FastAPI Docs: https://fastapi.tiangolo.com/
- Docker Compose: https://docs.docker.com/compose/
- PostgreSQL RLS: https://www.postgresql.org/docs/16/ddl-rowsecurity.html
- Celery: https://docs.celeryproject.io/
- Nginx: https://nginx.org/en/docs/
- Let's Encrypt: https://letsencrypt.org/docs/

---

**Deployment date**: 2026-06-01
