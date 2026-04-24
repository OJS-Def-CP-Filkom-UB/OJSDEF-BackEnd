# SOFTWARE REQUIREMENTS SPECIFICATION (SRS)
## OJSDef — OJS Integrated Security Scanner (SaaS)

---

| Atribut | Nilai |
|---|---|
| Versi Dokumen | 1.0 |
| Status | Draft for Internal Review |
| Tanggal | April 2026 |
| Berdasarkan | PRD OJSDef v1.0 |
| Mitra | Seclab Indonesia |
| Institusi | Universitas Brawijaya — Fakultas Ilmu Komputer |
| Tim | Kelompok 3 — Topik G2 |
| Klasifikasi | CONFIDENTIAL |

---

## Daftar Isi

1. [Pendahuluan](#1-pendahuluan)
2. [Deskripsi Keseluruhan Sistem](#2-deskripsi-keseluruhan-sistem)
3. [Arsitektur Sistem](#3-arsitektur-sistem)
4. [Desain Database](#4-desain-database)
5. [Technology Stack](#5-technology-stack)
6. [Kebutuhan Fungsional](#6-kebutuhan-fungsional)
7. [Kebutuhan Non-Fungsional](#7-kebutuhan-non-fungsional)
8. [Spesifikasi API](#8-spesifikasi-api)
9. [Alur Proses & Sequence Diagram](#9-alur-proses--sequence-diagram)
10. [Arsitektur Deployment (Docker)](#10-arsitektur-deployment-docker)
11. [Keamanan Sistem](#11-keamanan-sistem)
12. [Pengujian & Kriteria Penerimaan](#12-pengujian--kriteria-penerimaan)
13. [Batasan & Risiko Teknis](#13-batasan--risiko-teknis)
14. [Glosarium](#14-glosarium)

---

## 1. Pendahuluan

### 1.1 Tujuan Dokumen

Dokumen SRS ini mendefinisikan secara lengkap seluruh persyaratan teknis dan fungsional untuk pengembangan platform **OJSDef** — SaaS untuk audit keamanan dan pemindaian kerentanan pada instalasi Open Journal Systems (OJS). Dokumen ini menjadi acuan teknis bagi tim pengembang, mitra Seclab Indonesia, dan pemangku kepentingan akademik di Universitas Brawijaya.

SRS ini mencakup: arsitektur sistem, spesifikasi kebutuhan fungsional dan non-fungsional, desain basis data (ERD), spesifikasi API endpoint, sequence diagram, arsitektur deployment Docker, dan persyaratan keamanan sistem.

### 1.2 Ruang Lingkup Sistem

OJSDef melakukan pemindaian keamanan OJS dari **dua arah secara simultan**:

- **Arah Internal** — Plugin PHP yang terinstall di server OJS target, mengakses konfigurasi, file system, database, dan user role secara langsung dari dalam sistem.
- **Arah Eksternal** — Bot ofensif Python yang berjalan di server OJSDef, mensimulasikan pemindaian dari perspektif penyerang nyata.

Kedua hasil dikonsolidasikan oleh **Risk Scoring Engine** menggunakan CVSS v3 + OWASP, lalu disajikan melalui dashboard Next.js yang dapat dipahami pengguna non-teknis.

### 1.3 Definisi & Singkatan

| Istilah | Definisi |
|---|---|
| OJS | Open Journal Systems — platform open-source manajemen jurnal ilmiah (PKP) |
| SaaS | Software as a Service — model distribusi software berbasis cloud |
| CVE | Common Vulnerabilities and Exposures — penomoran standar kerentanan publik |
| CVSS v3 | Common Vulnerability Scoring System v3 — standar penilaian keparahan (0.0–10.0) |
| OWASP | Open Web Application Security Project |
| RLS | Row-Level Security — fitur PostgreSQL untuk isolasi data antar tenant |
| JWT | JSON Web Token — standar token autentikasi stateless |
| RBAC | Role-Based Access Control |
| HMAC | Hash-based Message Authentication Code |
| Celery | Distributed task queue untuk Python |
| FastAPI | Framework web Python async berkinerja tinggi |
| RSC | React Server Components (Next.js 14) |
| Tenant | Institusi/organisasi pengguna dalam arsitektur multi-tenant |
| Attack Surface | Keseluruhan titik sistem yang berpotensi menjadi vektor serangan |
| Defacement | Serangan yang mengubah tampilan website secara tidak sah |
| Content Injection | Penyisipan konten ilegal (judi online, malware) ke dalam sistem OJS |

### 1.4 Referensi

- PRD OJSDef v1.0 — Laporan Lembar Kerja 2, Topik G2, Kelompok 3 (2026)
- OWASP Top 10 2021: https://owasp.org/www-project-top-ten/
- CVSS v3.1 Specification: https://www.first.org/cvss/specification-document
- NVD CVE API: https://nvd.nist.gov/developers/vulnerabilities
- OJS Plugin Development Guide: https://docs.pkp.sfu.ca/
- FastAPI Documentation: https://fastapi.tiangolo.com/
- Next.js 14 Docs: https://nextjs.org/docs
- PostgreSQL 16 RLS: https://www.postgresql.org/docs/16/ddl-rowsecurity.html

---

## 2. Deskripsi Keseluruhan Sistem

### 2.1 Perspektif Produk

OJSDef adalah sistem SaaS mandiri (standalone) yang beroperasi sebagai lapisan keamanan tambahan di atas instalasi OJS yang sudah ada, tanpa memodifikasi atau mengganggu fungsionalitas OJS itu sendiri.

Interaksi dengan OJS terjadi melalui dua mekanisme:
1. Plugin PHP yang di-install di OJS dan mengirimkan data audit via HTTPS ke API Gateway OJSDef.
2. Bot eksternal yang memindai OJS dari sisi internet.

### 2.2 Fungsi Utama Sistem

| # | Fungsi | Deskripsi Singkat |
|---|---|---|
| F-01 | Dual-Direction Security Scan | Audit dari dalam (plugin) + luar (bot) secara terintegrasi |
| F-02 | Automated Vulnerability Detection | Deteksi otomatis berbasis rule set, pattern matching, CVE DB |
| F-03 | Risk Scoring & Prioritization | CVSS v3 per temuan, klasifikasi 4 level (Low/Medium/High/Critical) |
| F-04 | Attack Surface Mapping | Pemetaan endpoint publik, plugin aktif, komponen terekspos |
| F-05 | Security Dashboard | Visualisasi hasil scan untuk pengguna non-teknis |
| F-06 | Report Generation | Laporan PDF, JSON, HTML yang dapat diekspor |
| F-07 | Actionable Remediation | Panduan perbaikan step-by-step per temuan |
| F-08 | Real-time Alerting | Notifikasi Email + Telegram untuk kerentanan Critical |
| F-09 | Scan Scheduling | Eksekusi scan otomatis (cron) pada jam off-peak |
| F-10 | Multi-Tenant Management | Banyak institusi dalam satu platform, data terisolasi per RLS |

### 2.3 Kelas Pengguna & Hak Akses

| Role | Karakteristik | Hak Akses |
|---|---|---|
| `admin_ojs` | Pengelola jurnal, mungkin non-teknis | Scan, dashboard, report, kelola target & notifikasi |
| `it_admin` | Tim IT/DevOps server OJS | Semua admin_ojs + log teknis detail, jadwal scan |
| `saas_admin` | Administrator platform OJSDef | Super admin: kelola semua tenant, update CVE, monitoring |

### 2.4 Batasan Sistem

- Sistem **tidak** melakukan penetration testing aktif/destruktif yang merusak data.
- Scanning eksternal bersifat **pasif** — tidak ada payload berbahaya dikirimkan ke target.
- Plugin hanya mendukung **OJS 3.x** (3.3.x, 3.4.x) dengan PHP 7.4+/8.x.
- **Verifikasi kepemilikan domain wajib** dilakukan sebelum scan pertama.
- Rate limiting eksternal: maksimal **10 request/detik** ke server target.

---

## 3. Arsitektur Sistem

### 3.1 Gambaran Umum Arsitektur (Layered Architecture)

```mermaid
graph TB
    subgraph CLIENT["🖥️ CLIENT LAYER"]
        U1[Admin OJS<br/>Browser]
        U2[Tim IT<br/>Browser]
        U3[SaaS Admin<br/>Browser]
        FE["Next.js 14<br/>App Router + shadcn/ui"]
    end

    subgraph APP["⚙️ APPLICATION LAYER"]
        GW["API Gateway<br/>FastAPI 0.110 + Uvicorn"]
        AUTH["Auth Service<br/>JWT + RBAC"]
        BEAT["Celery Beat<br/>Scheduler"]

        subgraph WORKERS["Celery Workers"]
            WI["Internal Bot Worker<br/>Python — Plugin Processor"]
            WE["External Bot Worker<br/>Python — Offensive Scanner"]
            WS["Scoring Worker<br/>CVSS v3 + PDF Gen"]
            WN["Notify Worker<br/>Email + Telegram"]
        end
    end

    subgraph DB["🗄️ DATABASE LAYER"]
        PG["PostgreSQL 16<br/>Main DB — RLS Multi-Tenant"]
        RD["Redis 7<br/>Broker + Cache + Session"]
        MN["MinIO<br/>PDF Reports Storage"]
    end

    subgraph INFRA["🐳 INFRASTRUCTURE"]
        NG["Nginx<br/>Reverse Proxy + SSL"]
        DK["Docker Compose<br/>Container Orchestration"]
        PR["Prometheus + Grafana<br/>Monitoring"]
    end

    subgraph EXT["🌐 THIRD PARTY"]
        OJS["OJS Target<br/>PHP Plugin Installed"]
        CVE["NVD CVE API<br/>daily sync"]
        SMTP["SMTP / Telegram<br/>Notifications"]
    end

    U1 & U2 & U3 --> FE
    FE -- "HTTPS REST JSON" --> GW
    GW --> AUTH
    GW -- "enqueue" --> RD
    RD --> WI & WE & WS & WN
    BEAT -- "cron jobs" --> RD
    WI & WE & WS & WN --> PG
    WS --> MN
    WN --> SMTP
    WE -. "passive scan" .-> OJS
    OJS -. "HTTPS HMAC callback" .-> GW
    WI --> CVE
    GW --> PG
    NG --> FE & GW
    DK --> APP & DB & INFRA
```

### 3.2 Model Keamanan Dua Arah

```mermaid
graph LR
    subgraph TARGET["OJS Target Server"]
        direction TB
        PLG["🔌 OJSDef Plugin PHP<br/>(Installed)"]
        CFG["config.inc.php"]
        CORE["OJS Core Files<br/>(SHA-256 hash)"]
        PLUG["Plugin Registry"]
        USR["User & Role DB"]
        ART["DB Articles<br/>(Content)"]
        DIR["File System<br/>Directory"]
    end

    subgraph PLATFORM["OJSDef Platform"]
        direction TB
        IB["Internal Bot Worker<br/>🔵 Defensive"]
        EB["External Bot Worker<br/>🔴 Offensive"]
        SE["Risk Scoring Engine<br/>CVSS v3"]
        DB["Dashboard + Reports<br/>Next.js"]
        FEED["CVE Feed NVD"]
    end

    subgraph INTERNET["Internet / Attacker View"]
        direction TB
        EP["HTTP Endpoints"]
        SSL["SSL Certificate"]
        HDR["HTTP Headers"]
        VULN["SQLi / XSS Vectors"]
        OD["Open Directories"]
        API["Public API"]
    end

    PLG -. "HTTPS HMAC\nCallback" .-> IB
    PLG --> CFG & CORE & PLUG & USR & ART & DIR

    EB -. "Passive Scan\n≤10 req/s" .-> EP & SSL & HDR & VULN & OD & API

    IB --> SE
    EB --> SE
    FEED --> SE
    SE --> DB

    style IB fill:#1E40AF,color:#fff
    style EB fill:#C2410C,color:#fff
    style SE fill:#0F766E,color:#fff
    style DB fill:#1B3A6B,color:#fff
    style PLG fill:#D97706,color:#fff
```

### 3.3 Komponen Aplikasi Detail

#### 3.3.1 API Gateway (FastAPI)

Entry point tunggal untuk semua request. Bertanggung jawab atas:
- Autentikasi JWT via middleware
- Validasi request schema (Pydantic v2)
- Rate limiting per-tenant
- Routing ke service internal
- Enqueue task ke Celery via Redis

#### 3.3.2 Task Queue — Celery Workers

| Worker | Queue Name | Concurrency | Fungsi |
|---|---|---|---|
| `celery-worker-internal` | `internal_scan` | 4 | Proses data audit dari plugin OJS |
| `celery-worker-external` | `external_scan` | 2 | Jalankan scan ofensif eksternal (rate-limited) |
| `celery-worker-scoring` | `scoring` | 2 | Kalkulasi CVSS + generate PDF |
| `celery-worker-notify` | `notifications` | 4 | Dispatch email + Telegram |

#### 3.3.3 Internal Bot Worker — Scanner Modules

Plugin PHP ter-install di OJS dan mengirimkan payload JSON via HTTPS POST ke `/plugin/v1/callback`. Semua request ditandatangani HMAC-SHA256. Worker memproses:

| Modul | Data yang Diproses |
|---|---|
| Config Scanner | config.inc.php — debug mode, error reporting, secret key strength |
| Plugin Auditor | Plugin list — versi, CVE match, disabled-but-installed |
| RBAC Auditor | User + roles — privilege excess, inactive privileged accounts |
| File Integrity | SHA-256 file hash vs OJS official release checksums |
| Content Detector | DB articles — regex pattern judi/malware/iframe/redirect |
| DB Security | Credential strength, backup file exposure, SQL mode |

#### 3.3.4 External Bot Worker — Scanner Modules

Berjalan sepenuhnya dari server OJSDef, passive/read-only:

| Modul | Library Python | Yang Diperiksa |
|---|---|---|
| OJS Fingerprinting | `requests`, `BeautifulSoup4` | Versi OJS dari HTTP headers, meta tags, URL patterns |
| Endpoint Discovery | `requests`, `lxml` | Public endpoints, sitemaps, form actions |
| SSL/TLS Analysis | `ssl`, `pyopenssl`, `cryptography` | Cert validity, expiry, cipher suites, TLS version |
| HTTP Headers | `requests` | CSP, X-Frame-Options, HSTS, Referrer-Policy |
| Passive Vuln Probe | `requests`, `re` | Reflected XSS, SQL error disclosure, path traversal |
| Open Dir Detection | `requests` | /backup/, /.git/, .env, phpinfo.php, config files |
| CVE Matching | `nvdlib` | OJS + plugin version vs NVD CVE database |
| API Security | `requests` | Unauthenticated API endpoint, IDOR indicators |

### 3.4 Flow Arsitektur Keseluruhan

```mermaid
flowchart TD
    A([User Login]) --> B[Next.js Dashboard]
    B --> C{Request Type}

    C -->|Add Target| D[POST /api/v1/targets]
    C -->|Verify Domain| E[POST /api/v1/targets/:id/verify]
    C -->|Run Scan| F[POST /api/v1/scans]
    C -->|View Results| G[GET /api/v1/scans/:id]
    C -->|Download PDF| H[GET /api/v1/reports/:id/pdf]

    D & E & F & G & H --> I[FastAPI API Gateway]
    I --> J{Auth + RBAC Middleware}
    J -->|401/403| K[Error Response]
    J -->|OK| L{Route Handler}

    L -->|Target CRUD| M[(PostgreSQL)]
    L -->|Enqueue Scan| N[Redis Broker]

    N --> O{Scan Type}
    O -->|Internal| P[Internal Bot Worker]
    O -->|External| Q[External Bot Worker]
    O -->|Full| P & Q

    P --> R{Plugin Connected?}
    R -->|No| S[Status: Plugin Error]
    R -->|Yes| T[Request Plugin Callback]
    T --> U[Process Audit Data]

    Q --> V[Run Scanner Modules]
    V --> W[fingerprint + ssl + headers\nvuln_probe + open_dir + cve_match]

    U & W --> X[Scoring Worker]
    X --> Y[CVSS Calculation per Finding]
    Y --> Z[Overall Risk Score 0-100]
    Z --> AA[(Save to PostgreSQL)]
    Z --> AB{Risk Level?}
    AB -->|Critical| AC[Notify Worker]
    AC --> AD[Email + Telegram Alert]
    AB -->|Any| AE[Report Worker]
    AE --> AF[PDF Generation - WeasyPrint]
    AF --> AG[(MinIO Storage)]
    AA --> AH[Dashboard Ready]

    style P fill:#1E40AF,color:#fff
    style Q fill:#C2410C,color:#fff
    style X fill:#0F766E,color:#fff
    style AC fill:#059669,color:#fff
```

---

## 4. Desain Database

### 4.1 Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    tenants {
        uuid id PK
        varchar name
        varchar slug UK
        enum plan "free|pro|enterprise"
        int api_quota
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }

    users {
        uuid id PK
        uuid tenant_id FK
        varchar email UK
        text password_hash
        varchar full_name
        enum role "admin_ojs|it_admin|saas_admin"
        boolean is_active
        boolean notif_email
        boolean notif_telegram
        varchar telegram_chat_id
        timestamptz last_login
        timestamptz created_at
    }

    ojs_targets {
        uuid id PK
        uuid tenant_id FK
        uuid created_by FK
        varchar url UK
        varchar name
        varchar verification_token
        boolean is_verified
        text plugin_api_key "encrypted"
        boolean plugin_connected
        varchar ojs_version
        timestamptz plugin_last_seen
        timestamptz last_scan_at
        timestamptz created_at
    }

    scan_jobs {
        uuid id PK
        uuid target_id FK
        uuid initiated_by FK
        enum scan_type "internal|external|full"
        enum status "queued|running|completed|failed"
        varchar celery_task_id
        decimal overall_score "0-100"
        enum risk_level "low|medium|high|critical"
        int total_findings
        int critical_count
        int high_count
        int medium_count
        int low_count
        text error_message
        timestamptz started_at
        timestamptz completed_at
    }

    scan_findings {
        uuid id PK
        uuid job_id FK
        varchar finding_type
        enum category "internal|external"
        enum severity "low|medium|high|critical"
        decimal cvss_score
        varchar cve_id
        varchar owasp_category
        varchar title
        text description
        text affected_path
        text evidence
        text remediation
        boolean is_false_positive
        timestamptz created_at
    }

    scan_schedules {
        uuid id PK
        uuid target_id FK
        uuid created_by FK
        varchar cron_expression
        enum scan_type "internal|external|full"
        boolean is_active
        timestamptz next_run_at
        timestamptz last_run_at
        timestamptz created_at
    }

    reports {
        uuid id PK
        uuid job_id FK
        enum format "pdf|json|html"
        text file_url "MinIO path"
        int file_size_bytes
        timestamptz generated_at
        timestamptz expires_at
    }

    notifications {
        uuid id PK
        uuid job_id FK
        uuid user_id FK
        enum channel "email|telegram"
        enum type "critical_alert|scan_summary"
        jsonb payload
        boolean is_sent
        timestamptz sent_at
        text error_log
    }

    audit_logs {
        uuid id PK
        uuid user_id FK
        uuid tenant_id FK
        varchar action
        varchar resource_type
        uuid resource_id
        inet ip_address
        text user_agent
        jsonb metadata
        timestamptz created_at
    }

    tenants ||--o{ users : "has"
    tenants ||--o{ ojs_targets : "owns"
    users ||--o{ ojs_targets : "created_by"
    ojs_targets ||--o{ scan_jobs : "has"
    ojs_targets ||--o{ scan_schedules : "has"
    users ||--o{ scan_jobs : "initiated_by"
    users ||--o{ scan_schedules : "created_by"
    scan_jobs ||--o{ scan_findings : "contains"
    scan_jobs ||--o{ reports : "generates"
    scan_jobs ||--o{ notifications : "triggers"
    users ||--o{ notifications : "receives"
    users ||--o{ audit_logs : "generates"
    tenants ||--o{ audit_logs : "scoped_to"
```

### 4.2 Strategi Multi-Tenancy (Row-Level Security)

```sql
-- Semua tabel utama memiliki tenant_id
-- RLS Policy diterapkan di level PostgreSQL

ALTER TABLE ojs_targets ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON ojs_targets
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- FastAPI middleware meng-inject tenant_id ke setiap session:
-- SET app.current_tenant_id = '<uuid>';
```

Keuntungan RLS:
- Isolasi data antar institusi di level database (bukan hanya aplikasi)
- Mencegah bug aplikasi yang menyebabkan data antar tenant bocor
- Query otomatis terfilter tanpa perubahan kode aplikasi

### 4.3 Indexing Strategy

```sql
-- Performance indexes
CREATE INDEX idx_scan_jobs_target_id ON scan_jobs(target_id);
CREATE INDEX idx_scan_jobs_status ON scan_jobs(status);
CREATE INDEX idx_scan_findings_job_id ON scan_findings(job_id);
CREATE INDEX idx_scan_findings_severity ON scan_findings(severity);
CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_ojs_targets_tenant_id ON ojs_targets(tenant_id);

-- Partial index for active jobs
CREATE INDEX idx_scan_jobs_active ON scan_jobs(target_id, created_at)
    WHERE status IN ('queued', 'running');

-- Full-text search for findings
CREATE INDEX idx_findings_title_fts ON scan_findings
    USING gin(to_tsvector('english', title || ' ' || description));
```

---

## 5. Technology Stack

### 5.1 Stack Lengkap

```mermaid
graph LR
    subgraph FRONTEND["Frontend — Next.js 14"]
        NX["Next.js 14<br/>App Router + RSC"]
        RC["React 18<br/>shadcn/ui + Radix"]
        TW["TailwindCSS v3"]
        RQ["TanStack Query v5<br/>(data fetching)"]
        ZS["Zustand<br/>(global state)"]
        CH["Recharts<br/>(visualization)"]
        AX["Axios<br/>(HTTP client)"]
    end

    subgraph BACKEND["Backend — Python"]
        FA["FastAPI 0.110<br/>+ Uvicorn (ASGI)"]
        PD["Pydantic v2<br/>(validation)"]
        SA["SQLAlchemy 2.0<br/>(ORM async)"]
        AL["Alembic<br/>(migrations)"]
        JO["python-jose<br/>(JWT)"]
        BC["passlib[bcrypt]<br/>(password hash)"]
        CE["Celery 5<br/>(task queue)"]
        WP["WeasyPrint<br/>(PDF generation)"]
        J2["Jinja2<br/>(HTML templates)"]
    end

    subgraph SCANNER["Scanner Libraries"]
        RQ2["requests + httpx<br/>(HTTP scanner)"]
        BS["BeautifulSoup4<br/>(HTML parsing)"]
        SS["ssl + pyopenssl<br/>(TLS analysis)"]
        CR["cryptography<br/>(cert inspection)"]
        NV["nvdlib<br/>(CVE lookup)"]
        RE["re + validators<br/>(pattern matching)"]
    end

    subgraph DB["Data Layer"]
        PG["PostgreSQL 16<br/>(main database)"]
        RD["Redis 7<br/>(broker + cache)"]
        MN["MinIO<br/>(object storage)"]
    end

    subgraph INFRA["Infrastructure"]
        DK["Docker 24<br/>+ Compose v2"]
        NG["Nginx 1.25<br/>(reverse proxy)"]
        PM["Prometheus<br/>(metrics)"]
        GR["Grafana<br/>(dashboards)"]
        ST["Sentry<br/>(error tracking)"]
    end

    FRONTEND -- "REST JSON\nHTTPS" --> BACKEND
    BACKEND --> DB
    BACKEND --> SCANNER
    BACKEND --> INFRA
```

### 5.2 Justifikasi Pilihan Tech Stack

| Komponen | Pilihan | Justifikasi |
|---|---|---|
| **Frontend** | Next.js 14 | App Router + RSC untuk performa optimal; SSR untuk SEO; ekosistem React matang |
| **UI Components** | shadcn/ui + Radix | Accessible, customizable, tidak lock-in ke library tertentu |
| **Data Fetching** | TanStack Query v5 | Server state management terbaik untuk React; caching + background refetch |
| **Backend** | FastAPI | Async Python native; auto-generated OpenAPI docs; Pydantic v2 validation; performance tinggi |
| **ORM** | SQLAlchemy 2.0 async | Mature, production-ready, native async support, compatible dengan PostgreSQL |
| **Database** | PostgreSQL 16 | RLS untuk multi-tenancy; JSONB untuk flexible data; production-grade ACID |
| **Broker** | Redis 7 | Ultra-fast in-memory; digunakan dual purpose: Celery broker + cache + session |
| **Task Queue** | Celery 5 | De-facto standard Python async tasks; retry logic; monitoring via Flower |
| **PDF** | WeasyPrint | HTML/CSS → PDF conversion; mudah dikustomisasi dengan template |
| **Object Storage** | MinIO | S3-compatible self-hosted; tidak bergantung AWS; mudah di-deploy dengan Docker |
| **Reverse Proxy** | Nginx | Industry standard; SSL termination; rate limiting; static file serving |
| **Container** | Docker + Compose | Reproducible environment; mudah scaling; production deployment standard |
| **Monitoring** | Prometheus + Grafana | Stack monitoring open source terbaik; tidak ada biaya tambahan |
| **Error Tracking** | Sentry | Real-time error monitoring; stack trace detail; free tier memadai |

### 5.3 Versi Dependencies Backend (requirements.txt)

```
# Core
fastapi==0.110.0
uvicorn[standard]==0.29.0
pydantic==2.6.4
pydantic-settings==2.2.1

# Database
sqlalchemy==2.0.29
asyncpg==0.29.0
alembic==1.13.1
redis==5.0.3
aioredis==2.0.1

# Auth
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# Task Queue
celery==5.3.6
flower==2.0.1

# Scanner
requests==2.31.0
httpx==0.27.0
beautifulsoup4==4.12.3
lxml==5.1.0
pyopenssl==24.1.0
cryptography==42.0.5
nvdlib==0.7.6

# PDF & Storage
weasyprint==62.3
jinja2==3.1.3
boto3==1.34.0  # MinIO S3-compatible

# Notifications
httpx==0.27.0  # Telegram Bot API
aiosmtplib==3.0.1

# Utils
python-multipart==0.0.9
python-dotenv==1.0.1
sentry-sdk[fastapi]==1.44.0
```

### 5.4 Versi Dependencies Frontend (package.json)

```json
{
  "dependencies": {
    "next": "14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@tanstack/react-query": "^5.28.0",
    "zustand": "^4.5.2",
    "axios": "^1.6.7",
    "recharts": "^2.12.3",
    "@radix-ui/react-dialog": "^1.0.5",
    "tailwindcss": "^3.4.1",
    "shadcn-ui": "^0.8.0",
    "next-auth": "^5.0.0-beta",
    "react-hook-form": "^7.51.0",
    "zod": "^3.22.4",
    "date-fns": "^3.6.0",
    "lucide-react": "^0.363.0"
  }
}
```

---

## 6. Kebutuhan Fungsional

**Konvensi ID:** `FR-[MODUL]-[NOMOR]` | **Prioritas:** P1=Must Have, P2=Should Have, P3=Nice to Have

### 6.1 FR-AUTH — Autentikasi & Manajemen Pengguna

| ID | Deskripsi | Kriteria Penerimaan | Role | P |
|---|---|---|---|---|
| FR-AUTH-01 | Registrasi akun baru dengan email, password, nama. Email verifikasi dikirim sebelum akun aktif. | Akun tersimpan; email terkirim dalam 1 menit; login ditolak sebelum verifikasi. | Semua | P1 |
| FR-AUTH-02 | Login email+password mengembalikan access token (1 jam) dan refresh token (30 hari). | Login sukses → `access_token` + `refresh_token`; login gagal → 401 tanpa expose info email/password mana yang salah. | Semua | P1 |
| FR-AUTH-03 | Refresh access token tanpa login ulang menggunakan refresh token valid. | POST /auth/refresh → access_token baru; token expired → 401. | Semua | P1 |
| FR-AUTH-04 | RBAC: setiap endpoint diproteksi middleware yang memverifikasi role. | Akses tidak sah → 403 Forbidden; role check di level middleware. | Semua | P1 |
| FR-AUTH-05 | Ubah password dengan verifikasi password lama. | Password berubah; semua session lain di-invalidate kecuali current. | Semua | P1 |
| FR-AUTH-06 | Konfigurasi notifikasi: toggle email, set Telegram chat ID. | Preferensi tersimpan; berlaku untuk scan berikutnya. | Semua | P2 |
| FR-AUTH-07 | SaaS Admin mengelola tenant: create, suspend, delete. | Tenant suspend → login diblokir; delete → semua data terhapus setelah konfirmasi. | saas_admin | P1 |

### 6.2 FR-TARGET — Manajemen Target OJS

| ID | Deskripsi | Kriteria Penerimaan | Role | P |
|---|---|---|---|---|
| FR-TARGET-01 | Tambah target OJS: input URL + nama. Sistem validasi format URL dan ping konektivitas. | URL valid HTTPS; reachable dalam 10 detik; duplikat per tenant ditolak. | admin_ojs, it_admin | P1 |
| FR-TARGET-02 | Verifikasi kepemilikan domain wajib sebelum scan pertama. Dua metode: (a) file upload ke root OJS, (b) DNS TXT record. | File/DNS record terdeteksi → status `verified`; scan ditolak jika belum verified. | admin_ojs, it_admin | P1 |
| FR-TARGET-03 | Panduan interaktif instalasi plugin OJSDef: download ZIP, API key, instruksi konfigurasi. | Panduan menampilkan: link download, API key unik, step-by-step di OJS admin panel. | admin_ojs, it_admin | P1 |
| FR-TARGET-04 | Status koneksi plugin real-time: Connected/Disconnected/Error + waktu terakhir koneksi. | Ter-update setiap heartbeat plugin (5 menit); Disconnected jika > 15 menit tanpa heartbeat. | admin_ojs, it_admin | P1 |
| FR-TARGET-05 | Edit nama target; delete target beserta semua scan history-nya. | Delete memerlukan konfirmasi teks; semua data terkait terhapus. | admin_ojs, it_admin | P2 |
| FR-TARGET-06 | Multi-target: satu akun kelola lebih dari satu OJS. Dibatasi per subscription plan. | Free: maks 1; Pro: maks 10; Enterprise: unlimited. | admin_ojs, it_admin | P2 |

### 6.3 FR-INT — Internal Security Scan (Plugin-Based)

Plugin PHP mengirim payload JSON via POST ke `/plugin/v1/callback` dengan HMAC-SHA256 signature.

| ID | Sub-Modul | Deskripsi | Output Finding | P |
|---|---|---|---|---|
| FR-INT-01 | OJS Fingerprinting | Deteksi versi OJS dari `PKP_APP_VERSION`, `version.xml`. Compare dengan latest release GitHub. List semua plugin terinstall. | Versi OJS; gap versi; list plugin+status | P1 |
| FR-INT-02 | Configuration Scanner | Baca `config.inc.php`: debug_mode, error_reporting, secret_key strength, SMTP credential exposure, database config. | List konfigurasi bermasalah + severity | P1 |
| FR-INT-03 | Plugin Security Audit | Deteksi: (a) plugin outdated tanpa CVE, (b) plugin dengan CVE aktif, (c) plugin disabled-but-installed (dead code), (d) plugin sumber tidak dikenal. | List plugin + status keamanan | P1 |
| FR-INT-04 | RBAC Auditor | Query tabel `users`, `roles`, `user_user_groups`. Deteksi: privilege berlebih, akun tidak aktif >1 tahun dengan role admin, multiple super-admin. | List user bermasalah (tanpa PII sensitif) | P1 |
| FR-INT-05 | File Integrity Checker | Bandingkan SHA-256 hash file OJS vs checksums resmi dari OJS GitHub release. Deteksi: modified, unknown, missing files. | List file + status (ok/modified/unknown/missing) | P1 |
| FR-INT-06 | Content Injection Detector | Query DB OJS tabel `articles`, `submissions`. Deteksi pola: URL judi online, keyword gambling (regex), iframe tersembunyi, script redirect berbahaya. | List artikel terindikasi + excerpt bukti | P1 |
| FR-INT-07 | Database Security Check | Cek: DB user dengan hak berlebih (root), backup file .sql di web-accessible directory, SQL mode konfigurasi. | List konfigurasi DB bermasalah | P2 |
| FR-INT-08 | Weak Credentials Detector | Cek hash password admin vs daftar common passwords top-10000. PHP `password_verify()` untuk bcrypt, atau check langsung untuk SHA1. | Daftar akun dengan password lemah | P2 |

### 6.4 FR-EXT — External Security Scan (Bot Ofensif)

Berjalan dari server OJSDef. Passive/read-only. Rate limit: 10 req/detik ke target.

| ID | Sub-Modul | Deskripsi | Tools Python | P |
|---|---|---|---|---|
| FR-EXT-01 | OJS Fingerprinting | Deteksi versi OJS dari HTTP headers (`X-Powered-By`), HTML meta tags (`generator`), URL patterns, file markers. | `requests`, `BeautifulSoup4` | P1 |
| FR-EXT-02 | Endpoint Discovery | Crawling endpoint publik: login, submission form, `/api/v1/`, admin paths, upload forms. Parse `sitemap.xml` jika ada. | `requests`, `lxml` | P1 |
| FR-EXT-03 | SSL/TLS Analysis | Validity, expiry (<30 hari=warning, expired=critical), cipher suites, protokol (TLS 1.0/1.1=deprecated), HSTS presence. | `ssl`, `pyopenssl`, `cryptography` | P1 |
| FR-EXT-04 | HTTP Security Headers | Periksa: CSP, X-Frame-Options, X-XSS-Protection, HSTS, Referrer-Policy, Permissions-Policy. Deteksi nilai konfigurasi lemah. | `requests` | P1 |
| FR-EXT-05 | Passive Vuln Probing | Reflected XSS detection pada query params, SQL error disclosure, path traversal indicators, open redirect check, CSRF absence. | `requests`, `re` | P1 |
| FR-EXT-06 | Open Directory Detection | Akses: `/backup/`, `/.git/`, `/.env`, `/phpinfo.php`, `/config/`, `wp-config.php`, `/install/`. Tanpa bruteforce. | `requests` | P1 |
| FR-EXT-07 | CVE Matching | Match versi OJS + plugin yang terdeteksi dengan NVD CVE API. Return CVE ID, CVSS score, dan deskripsi. | `nvdlib`, `requests` | P1 |
| FR-EXT-08 | API Security Testing | Test endpoint API publik OJS: unauthenticated access, data leakage di response, IDOR indicators pada endpoint dengan ID. | `requests`, `httpx` | P2 |

### 6.5 FR-SCORE — Risk Scoring Engine

| ID | Deskripsi | Detail | P |
|---|---|---|---|
| FR-SCORE-01 | Hitung CVSS v3 base score untuk setiap finding berdasarkan: Attack Vector, Attack Complexity, Privileges Required, User Interaction, Scope, Confidentiality/Integrity/Availability Impact. | CVSS Calculator menggunakan formula resmi FIRST.org. | P1 |
| FR-SCORE-02 | Klasifikasikan setiap finding ke 4 level: Low (0.1–3.9), Medium (4.0–6.9), High (7.0–8.9), Critical (9.0–10.0). | Threshold mengikuti NVD CVSS v3 rating scale. | P1 |
| FR-SCORE-03 | Hitung overall security score (0–100) dari agregasi seluruh finding dengan pembobotan berdasarkan severity. | Formula: `100 - Σ(weight × count)` dimana Critical=30, High=15, Medium=5, Low=1, capped at 0. | P1 |
| FR-SCORE-04 | Generate action plan terurut berdasarkan severity (Critical dahulu) dengan langkah perbaikan dan estimasi waktu. | Setiap finding memiliki template remediation yang dapat dikustomisasi per kategori temuan. | P1 |
| FR-SCORE-05 | Trigger notifikasi otomatis jika terdapat temuan Critical. | Notifikasi terkirim via Notify Worker dalam <5 menit setelah scoring selesai. | P1 |

**Klasifikasi Risiko & SLA Perbaikan:**

| Level | CVSS Score | Kriteria Contoh | SLA Perbaikan |
|---|---|---|---|
| 🔴 Critical | 9.0 – 10.0 | File core termodifikasi, konten judi terdeteksi, RCE, RBAC bypass | Notifikasi langsung + patching dalam 24 jam |
| 🟠 High | 7.0 – 8.9 | SQL injection terdeteksi, CVE aktif, SSL expired, admin default password | Patching dalam 7 hari kerja |
| 🟡 Medium | 4.0 – 6.9 | Plugin outdated tanpa CVE, header CSP hilang, debug mode aktif | Action plan, patching dalam 30 hari |
| 🟢 Low | 0.1 – 3.9 | Versi OJS terekspos di headers, minor config best practice | Dokumentasikan, perbaiki saat maintenance |

### 6.6 FR-DASH — Dashboard Monitoring

| ID | Widget/Komponen | Deskripsi | P |
|---|---|---|---|
| FR-DASH-01 | Security Score Card | Skor 0–100 + indikator warna (merah/kuning/hijau) + label teks (Kritis/Berbahaya/Perhatian/Aman). Breakdown skor per kategori: Internal + External. | P1 |
| FR-DASH-02 | Vulnerability Summary Chart | Bar/donut chart jumlah temuan per severity (Critical/High/Medium/Low). Clickable untuk drill-down ke detail finding. | P1 |
| FR-DASH-03 | Attack Surface Map | Visualisasi endpoint dan komponen yang teridentifikasi saat scan. Menampilkan endpoint publik, plugin aktif, area berisiko. | P1 |
| FR-DASH-04 | Scan History Timeline | Timeline hasil scan terbaru: timestamp, scan type, status, overall score per scan. | P1 |
| FR-DASH-05 | Action Plan List | Daftar prioritas perbaikan berdasarkan severity. Setiap item: deskripsi masalah, dampak, langkah perbaikan step-by-step dalam Bahasa Indonesia, estimasi waktu. | P1 |
| FR-DASH-06 | Plugin Connection Status | Indikator real-time status plugin (Connected/Disconnected/Error) + waktu terakhir koneksi. | P1 |
| FR-DASH-07 | Compliance Checklist | Visual checklist kepatuhan terhadap OWASP Top 10 dan security baseline. Centang hijau/merah per kategori. | P2 |
| FR-DASH-08 | Scan Progress Indicator | Progress bar real-time saat scan sedang berjalan, menampilkan modul mana yang sedang dieksekusi. | P2 |

### 6.7 FR-REPORT — Report & Notifikasi

| ID | Fitur | Deskripsi | P |
|---|---|---|---|
| FR-REPORT-01 | PDF Report Generator | Laporan scan lengkap dalam format PDF siap cetak via WeasyPrint. Isi: executive summary, tabel kerentanan per severity, attack surface map, action plan. | P1 |
| FR-REPORT-02 | Executive Summary | Laporan ringkas 1–2 halaman untuk Pimpinan Institusi. Tanpa istilah teknis; fokus pada risiko bisnis dan rekomendasi prioritas. | P2 |
| FR-REPORT-03 | JSON Export | Export data scan dalam format JSON terstruktur untuk integrasi dengan SIEM atau sistem lain. | P2 |
| FR-REPORT-04 | Critical Alert Notification | Email dan/atau Telegram terkirim <5 menit setelah kerentanan Critical terdeteksi. Isi: deskripsi temuan, URL affected, langkah mitigasi segera. | P1 |
| FR-REPORT-05 | Scan Completion Summary | Email ringkasan setelah scan selesai: jumlah temuan per severity, overall score, link ke dashboard. | P2 |
| FR-REPORT-06 | Scan Scheduling | Pengguna set jadwal scan otomatis via cron expression. Interface picker untuk daily/weekly + jam eksekusi. | P2 |

---

## 7. Kebutuhan Non-Fungsional

### 7.1 Performa

| ID | Aspek | Kebutuhan | Kriteria Penerimaan |
|---|---|---|---|
| NFR-PERF-01 | Waktu respons API | Semua endpoint API merespons dalam < 500ms pada kondisi normal | Validasi: load test dengan Locust, P95 < 500ms |
| NFR-PERF-02 | Dashboard load time | Dashboard initial load < 3 detik pada koneksi 10Mbps | Validasi: Lighthouse Performance Score > 80 |
| NFR-PERF-03 | Durasi Internal Scan | Internal scan selesai < 5 menit untuk instalasi OJS normal | Validasi: end-to-end test dengan OJS standar |
| NFR-PERF-04 | Durasi External Scan | External scan selesai < 15 menit untuk target normal | Validasi: end-to-end test dengan URL publik |
| NFR-PERF-05 | Concurrent scans | Sistem mendukung 20 scan job berjalan bersamaan tanpa degradasi | Validasi: stress test dengan 20 concurrent scan requests |
| NFR-PERF-06 | Anti-DoS ke target | Rate limit external bot maks 10 req/detik ke setiap target | Validasi: tcpdump monitoring saat scan berjalan |

### 7.2 Keamanan

| ID | Aspek | Kebutuhan | Implementasi |
|---|---|---|---|
| NFR-SEC-01 | Autentikasi | JWT dengan TTL 1 jam; refresh token 30 hari; semua endpoint terproteksi | `python-jose`; middleware FastAPI; Redis token blacklist |
| NFR-SEC-02 | Enkripsi at-rest | Semua data scan terenkripsi di database | PostgreSQL column encryption untuk `plugin_api_key` |
| NFR-SEC-03 | Enkripsi in-transit | Semua komunikasi via HTTPS/TLS 1.3 minimum | Nginx SSL termination; Let's Encrypt; HSTS header |
| NFR-SEC-04 | Plugin security | HMAC-SHA256 signing untuk setiap request dari plugin ke API | Validasi signature di FastAPI middleware sebelum proses |
| NFR-SEC-05 | Data isolation | Isolasi data antar tenant di level database | PostgreSQL RLS; tenant_id di semua query |
| NFR-SEC-06 | Input validation | Semua input divalidasi sebelum diproses | Pydantic v2 schema validation di setiap endpoint |
| NFR-SEC-07 | API key storage | Plugin API key disimpan terenkripsi | AES-256-GCM encryption dengan key dari environment variable |
| NFR-SEC-08 | Domain ownership | Scan hanya dilakukan pada domain yang sudah diverifikasi | is_verified flag; middleware check sebelum enqueue |

### 7.3 Ketersediaan & Skalabilitas

| ID | Aspek | Kebutuhan |
|---|---|---|
| NFR-AVAIL-01 | Uptime SLA | 99.5% per bulan (maks downtime 3.6 jam/bulan) |
| NFR-AVAIL-02 | On-demand access | Platform dapat diakses 24/7 tanpa maintenance window yang memblokir akses |
| NFR-AVAIL-03 | Concurrent users | Mendukung 100+ concurrent user tanpa degradasi performa |
| NFR-AVAIL-04 | Multi-tenant | 50+ tenant aktif secara bersamaan |
| NFR-AVAIL-05 | CVE update | Database CVE diperbarui otomatis harian dari NVD API |

### 7.4 Usability

| ID | Aspek | Kebutuhan |
|---|---|---|
| NFR-USE-01 | Non-teknis | 80% pengguna non-teknis dapat membaca dan memahami risk score tanpa panduan tambahan |
| NFR-USE-02 | Bahasa mitigasi | Semua rekomendasi perbaikan ditulis dalam Bahasa Indonesia yang sederhana |
| NFR-USE-03 | Browser support | Chrome 100+, Firefox 100+, Edge 100+, Safari 15+ |
| NFR-USE-04 | Onboarding | Pengguna baru dapat menambah target dan menjalankan scan pertama < 30 menit |
| NFR-USE-05 | Mobile | Dashboard responsive dan dapat diakses di mobile browser |

### 7.5 Kompatibilitas

| ID | Aspek | Kebutuhan |
|---|---|---|
| NFR-COMPAT-01 | OJS Version | OJS 3.3.x dan 3.4.x |
| NFR-COMPAT-02 | PHP Version | PHP 7.4+, PHP 8.0, PHP 8.1, PHP 8.2 (di server OJS target) |
| NFR-COMPAT-03 | Server OS | Ubuntu 22.04+ untuk server OJSDef |

---

## 8. Spesifikasi API

### 8.1 Base URL & Versioning

```
Base URL  : https://api.ojsdef.id
Versioning: /api/v1/
Plugin CB : /plugin/v1/
Auth      : Bearer <JWT access_token> di Authorization header
```

### 8.2 Authentication Endpoints

```
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
POST /api/v1/auth/verify-email
POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
GET  /api/v1/auth/me
PUT  /api/v1/auth/me
PUT  /api/v1/auth/change-password
```

**Contoh Request & Response — POST /api/v1/auth/login:**

```json
// Request
{
  "email": "admin@universitas.ac.id",
  "password": "SecureP@ssword123"
}

// Response 200 OK
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@universitas.ac.id",
    "full_name": "Dr. Ahmad Surya",
    "role": "admin_ojs",
    "tenant_id": "660e8400-e29b-41d4-a716-446655440001"
  }
}
```

### 8.3 Target Management Endpoints

```
GET    /api/v1/targets                    # List semua target milik tenant
POST   /api/v1/targets                    # Tambah target baru
GET    /api/v1/targets/:id                # Detail satu target
PUT    /api/v1/targets/:id                # Update target
DELETE /api/v1/targets/:id                # Hapus target + scan history

POST   /api/v1/targets/:id/verify         # Trigger verifikasi kepemilikan domain
GET    /api/v1/targets/:id/verify-status  # Cek status verifikasi
GET    /api/v1/targets/:id/plugin-guide   # Panduan instalasi plugin
POST   /api/v1/targets/:id/regenerate-key # Regenerate API key plugin
```

**Contoh POST /api/v1/targets:**

```json
// Request
{
  "url": "https://jurnal.universitas.ac.id",
  "name": "Jurnal Ilmu Komputer Universitas Brawijaya"
}

// Response 201 Created
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "url": "https://jurnal.universitas.ac.id",
  "name": "Jurnal Ilmu Komputer Universitas Brawijaya",
  "is_verified": false,
  "plugin_connected": false,
  "plugin_api_key": "ojsdef_pk_live_abc123xyz...",
  "verification_token": "ojsdef-verify-a1b2c3d4e5f6",
  "verification_instructions": {
    "file_method": {
      "url": "https://jurnal.universitas.ac.id/ojsdef-verify-a1b2c3d4e5f6.txt",
      "content": "ojsdef-verification=a1b2c3d4e5f6"
    },
    "dns_method": {
      "type": "TXT",
      "host": "@",
      "value": "ojsdef-verify=a1b2c3d4e5f6"
    }
  },
  "created_at": "2026-04-14T08:00:00Z"
}
```

### 8.4 Scan Endpoints

```
POST   /api/v1/scans                      # Jalankan scan baru
GET    /api/v1/scans                      # List scan history (dengan filter)
GET    /api/v1/scans/:id                  # Detail scan + findings
GET    /api/v1/scans/:id/findings         # Findings dengan pagination + filter severity
PATCH  /api/v1/scans/:id/findings/:fid    # Mark finding sebagai false positive
DELETE /api/v1/scans/:id                  # Hapus scan record
```

**Contoh POST /api/v1/scans:**

```json
// Request
{
  "target_id": "770e8400-e29b-41d4-a716-446655440002",
  "scan_type": "full"  // "internal" | "external" | "full"
}

// Response 202 Accepted
{
  "job_id": "880e8400-e29b-41d4-a716-446655440003",
  "status": "queued",
  "scan_type": "full",
  "target": {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "url": "https://jurnal.universitas.ac.id"
  },
  "estimated_duration_seconds": 600,
  "message": "Scan dijadwalkan. Anda akan menerima notifikasi saat selesai.",
  "created_at": "2026-04-14T08:05:00Z"
}
```

**Contoh GET /api/v1/scans/:id (Completed):**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "target_id": "770e8400-e29b-41d4-a716-446655440002",
  "scan_type": "full",
  "status": "completed",
  "overall_score": 42.5,
  "risk_level": "high",
  "summary": {
    "total_findings": 18,
    "critical_count": 1,
    "high_count": 3,
    "medium_count": 8,
    "low_count": 6
  },
  "findings": [
    {
      "id": "990e8400-e29b-41d4-a716-446655440004",
      "category": "internal",
      "finding_type": "content_injection",
      "severity": "critical",
      "cvss_score": 9.1,
      "cve_id": null,
      "owasp_category": "A03:2021 – Injection",
      "title": "Konten Judi Online Terdeteksi di 3 Artikel",
      "description": "Ditemukan sisipan URL judi online dan script redirect pada 3 artikel di database OJS.",
      "affected_path": "/articles/id/123, /articles/id/456, /articles/id/789",
      "evidence": "URL: 'bet365-promo.xyz' ditemukan di konten artikel ID 123",
      "remediation": "1. Login ke OJS Admin Panel...\n2. Hapus konten terinfeksi...",
      "is_false_positive": false
    }
  ],
  "attack_surface": {
    "public_endpoints": 14,
    "exposed_api_endpoints": 6,
    "installed_plugins": 8,
    "outdated_plugins": 3
  },
  "report_url": "https://api.ojsdef.id/api/v1/reports/abc123/pdf",
  "started_at": "2026-04-14T08:05:30Z",
  "completed_at": "2026-04-14T08:14:22Z"
}
```

### 8.5 Report & Schedule Endpoints

```
GET  /api/v1/reports/:id/pdf              # Download laporan PDF
GET  /api/v1/reports/:id/json             # Export data JSON
GET  /api/v1/reports/:id/executive        # Executive summary PDF

GET    /api/v1/schedules                  # List semua jadwal scan
POST   /api/v1/schedules                  # Buat jadwal baru
GET    /api/v1/schedules/:id
PUT    /api/v1/schedules/:id
DELETE /api/v1/schedules/:id
POST   /api/v1/schedules/:id/toggle       # Aktifkan/nonaktifkan jadwal
```

### 8.6 Plugin Callback Endpoint

Endpoint ini dipanggil oleh plugin PHP OJS, bukan oleh frontend.

```
POST /plugin/v1/callback
```

```json
// Request Headers
{
  "X-OJSDef-Signature": "sha256=<hmac_hex>",
  "X-OJSDef-Target-ID": "770e8400-e29b-41d4-a716-446655440002",
  "X-OJSDef-Timestamp": "1713081600",
  "Content-Type": "application/json"
}

// Request Body
{
  "event": "audit_data",
  "target_id": "770e8400-e29b-41d4-a716-446655440002",
  "job_id": "880e8400-e29b-41d4-a716-446655440003",
  "timestamp": "2026-04-14T08:06:00Z",
  "data": {
    "ojs_version": "3.4.0.3",
    "php_version": "8.1.27",
    "config": {
      "debug_mode": false,
      "error_reporting": "E_ALL",
      "password_encryption": "bcrypt"
    },
    "plugins": [
      { "name": "customLocale", "version": "3.3.0.1", "enabled": true },
      { "name": "staticPages", "version": "1.3.0.0", "enabled": false }
    ],
    "file_integrity": {
      "checked": 847,
      "modified": 2,
      "unknown": 5,
      "missing": 0
    }
  }
}

// Response 202 Accepted
{ "status": "received", "queued": true }
```

### 8.7 Dashboard Stats Endpoint

```
GET /api/v1/dashboard/stats
```

```json
{
  "tenant_id": "660e8400-e29b-41d4-a716-446655440001",
  "period": "last_30_days",
  "targets": {
    "total": 3,
    "verified": 3,
    "plugin_connected": 2
  },
  "scans": {
    "total": 12,
    "completed": 11,
    "failed": 1,
    "last_scan_at": "2026-04-14T08:14:22Z"
  },
  "security_posture": {
    "average_score": 58.3,
    "score_trend": "+12.5",
    "worst_target": "jurnal.universitas.ac.id",
    "worst_score": 42.5
  },
  "findings_summary": {
    "critical_open": 1,
    "high_open": 5,
    "medium_open": 14,
    "low_open": 23,
    "resolved_this_month": 8
  }
}
```

---

## 9. Alur Proses & Sequence Diagram

### 9.1 User Registration & Target Setup

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Next.js
    participant API as FastAPI
    participant DB as PostgreSQL
    participant EMAIL as SMTP

    U->>FE: Isi form registrasi
    FE->>API: POST /auth/register
    API->>API: Validate Pydantic schema
    API->>API: Hash password (bcrypt)
    API->>DB: INSERT users (is_active=false)
    API->>EMAIL: Kirim email verifikasi
    API-->>FE: 201 Created
    FE-->>U: "Cek email Anda"

    U->>API: GET /auth/verify-email?token=xxx
    API->>DB: UPDATE users SET is_active=true
    API-->>U: Redirect ke login

    U->>FE: Login
    FE->>API: POST /auth/login
    API->>DB: SELECT user by email
    API->>API: verify password (bcrypt)
    API->>API: Generate JWT + refresh token
    API-->>FE: {access_token, refresh_token}
    FE->>FE: Store tokens (httpOnly cookie)
    FE-->>U: Dashboard
```

### 9.2 Domain Verification Flow

```mermaid
sequenceDiagram
    actor U as Admin OJS
    participant FE as Next.js
    participant API as FastAPI
    participant DB as PostgreSQL
    participant OJS as OJS Server

    U->>FE: Tambah URL target baru
    FE->>API: POST /api/v1/targets {url, name}
    API->>API: Validate URL format + ping
    API->>DB: INSERT ojs_targets (is_verified=false)
    API->>API: Generate verification_token
    API-->>FE: {target_id, verification_token, instructions}
    FE-->>U: Tampilkan instruksi verifikasi

    alt File Method
        U->>OJS: Upload ojsdef-verify-xxx.txt ke root
        U->>FE: Klik "Verifikasi Sekarang"
        FE->>API: POST /targets/:id/verify
        API->>OJS: GET /.../ojsdef-verify-xxx.txt
        OJS-->>API: 200 + konten file
        API->>API: Validasi konten token
    else DNS Method
        U->>OJS: Tambah DNS TXT record
        FE->>API: POST /targets/:id/verify
        API->>API: DNS TXT lookup
        API->>API: Validasi nilai TXT
    end

    API->>DB: UPDATE ojs_targets SET is_verified=true
    API-->>FE: {verified: true}
    FE-->>U: "Domain terverifikasi ✓"
```

### 9.3 Full Scan Execution Flow

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Next.js
    participant API as FastAPI
    participant RD as Redis Broker
    participant WI as Internal Worker
    participant WE as External Worker
    participant OJS as OJS Plugin
    participant WS as Scoring Worker
    participant WN as Notify Worker
    participant DB as PostgreSQL
    participant MN as MinIO

    U->>FE: Klik "Run Full Scan"
    FE->>API: POST /api/v1/scans {target_id, type:"full"}
    API->>API: Auth + verify domain ownership
    API->>DB: INSERT scan_jobs (status=queued)
    API->>RD: enqueue internal_scan_task + external_scan_task
    API-->>FE: 202 {job_id, status: queued}
    FE-->>U: Show scanning progress indicator

    par Internal Scan
        RD->>WI: Consume internal_scan_task
        WI->>DB: UPDATE job status=running
        WI->>OJS: Request plugin to send audit data
        OJS->>API: POST /plugin/v1/callback {audit_data}
        API->>RD: enqueue process_plugin_data
        RD->>WI: Process plugin audit data
        WI->>WI: Run: config, rbac, integrity, content, db checks
        WI->>DB: INSERT scan_findings (category=internal)
    and External Scan
        RD->>WE: Consume external_scan_task
        WE->>WE: Run: fingerprint, ssl, headers, vuln, open_dir, cve
        note over WE: Rate limit: ≤10 req/s to OJS target
        WE->>DB: INSERT scan_findings (category=external)
    end

    WI->>RD: Signal internal_done
    WE->>RD: Signal external_done
    RD->>WS: Consume scoring_task (after both done)
    WS->>DB: SELECT all findings for job
    WS->>WS: Calculate CVSS per finding
    WS->>WS: Calculate overall_score (0-100)
    WS->>WS: Generate action_plan
    WS->>WS: Render PDF (WeasyPrint + Jinja2)
    WS->>MN: Upload PDF report
    WS->>DB: UPDATE scan_job (status=completed, score, level, report_url)

    alt Critical Findings Exist
        WS->>RD: enqueue notification_task
        RD->>WN: Consume notification_task
        WN->>WN: Send Email + Telegram alert
        WN->>DB: INSERT notifications (sent=true)
    end

    FE->>API: GET /api/v1/scans/:id (polling)
    API->>DB: SELECT scan_job + findings
    API-->>FE: Full scan results
    FE-->>U: Render dashboard with results
```

### 9.4 Plugin Heartbeat & Status Flow

```mermaid
sequenceDiagram
    participant OJS as OJS Plugin (PHP)
    participant API as FastAPI
    participant DB as PostgreSQL
    participant RD as Redis

    loop Every 5 Minutes
        OJS->>API: POST /plugin/v1/heartbeat {target_id, version}
        API->>API: Validate HMAC signature
        API->>DB: UPDATE ojs_targets SET plugin_last_seen=now()
        API->>RD: Cache plugin_status:target_id = "connected" TTL=900s
        API-->>OJS: 200 {status: "ok"}
    end

    note over RD: If no heartbeat for 15 min,\ncache expires → status = Disconnected
    
    FE->>API: GET /targets/:id/plugin-status
    API->>RD: GET plugin_status:target_id
    alt Cache exists
        RD-->>API: "connected"
        API-->>FE: {status: "connected", last_seen: "..."}
    else Cache miss
        API->>DB: SELECT plugin_last_seen
        API-->>FE: {status: "disconnected", last_seen: "..."}
    end
```

### 9.5 Scan Scheduling Flow (Celery Beat)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant DB as PostgreSQL
    participant BEAT as Celery Beat
    participant RD as Redis
    participant WW as Workers

    U->>API: POST /api/v1/schedules {target_id, cron: "0 2 * * *", type: "full"}
    API->>DB: INSERT scan_schedules {cron, is_active: true}
    API->>BEAT: Register periodic task (dynamic scheduling)
    API-->>U: Schedule created

    loop Every minute
        BEAT->>DB: SELECT active schedules where next_run_at <= now()
        DB-->>BEAT: [schedule_1, schedule_2]
        BEAT->>DB: INSERT scan_jobs (status=queued)
        BEAT->>RD: enqueue scan tasks
        BEAT->>DB: UPDATE next_run_at = next_cron_tick
    end

    RD->>WW: Workers execute scans
    WW->>DB: Save results
```

---

## 10. Arsitektur Deployment (Docker)

### 10.1 Docker Compose Architecture

```mermaid
graph TB
    subgraph INTERNET["🌐 Internet"]
        CLIENT["Browser / Plugin Callback"]
    end

    subgraph HOST["🖥️ Ubuntu 22.04 Server"]
        subgraph DOCKER["Docker Network: ojsdef_net"]

            NGINX["nginx:1.25-alpine<br/>Port: 80→443<br/>SSL Termination"]

            subgraph FRONTEND["Frontend Container"]
                NX["nextjs-frontend<br/>node:20-alpine<br/>Internal: 3000"]
            end

            subgraph BACKEND["Backend Containers"]
                API["fastapi-backend<br/>python:3.11-slim<br/>Internal: 8000"]
                BEAT["celery-beat<br/>python:3.11-slim<br/>Scheduler"]
            end

            subgraph WORKERS["Worker Containers"]
                WI["worker-internal<br/>python:3.11-slim<br/>concurrency=4"]
                WE["worker-external<br/>python:3.11-slim<br/>concurrency=2"]
                WS["worker-scoring<br/>python:3.11-slim<br/>concurrency=2"]
                WN["worker-notify<br/>python:3.11-slim<br/>concurrency=4"]
            end

            subgraph DATA["Data Containers"]
                PG["postgres:16-alpine<br/>Internal: 5432"]
                RD["redis:7-alpine<br/>Internal: 6379"]
                MN["minio/minio<br/>Internal: 9000"]
            end

            subgraph OBS["Observability"]
                PR["prom/prometheus<br/>Internal: 9090"]
                GR["grafana/grafana<br/>Internal: 3001"]
                FL["mher/flower<br/>Celery Monitor<br/>Internal: 5555"]
            end
        end

        subgraph VOLUMES["📁 Docker Volumes (Persistent)"]
            V1["postgres_data"]
            V2["redis_data"]
            V3["minio_data"]
            V4["nginx_certs"]
            V5["grafana_data"]
        end
    end

    CLIENT --> NGINX
    NGINX -->|"/"|NX
    NGINX -->|"/api/"|API
    NGINX -->|"/plugin/"|API
    API --> RD
    API --> PG
    BEAT --> RD
    RD --> WI & WE & WS & WN
    WI & WE & WS & WN --> PG
    WS --> MN
    PR --> API & WI & WE & WS & WN
    GR --> PR
    FL --> RD

    PG --- V1
    RD --- V2
    MN --- V3
    NGINX --- V4
    GR --- V5

    style NGINX fill:#16A34A,color:#fff
    style API fill:#0369A1,color:#fff
    style NX fill:#1B3A6B,color:#fff
    style PG fill:#22C55E,color:#fff
    style RD fill:#DC2626,color:#fff
    style WI fill:#1E40AF,color:#fff
    style WE fill:#C2410C,color:#fff
    style WS fill:#0F766E,color:#fff
    style WN fill:#059669,color:#fff
```

### 10.2 docker-compose.yml (Production)

```yaml
version: '3.9'

services:
  # ── Reverse Proxy ──────────────────────────────
  nginx:
    image: nginx:1.25-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - nginx_certs:/etc/letsencrypt
      - nginx_webroot:/var/www/certbot
    depends_on:
      - nextjs-frontend
      - fastapi-backend
    restart: always

  # ── Frontend ───────────────────────────────────
  nextjs-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod
    environment:
      - NEXT_PUBLIC_API_URL=https://api.ojsdef.id
      - NEXTAUTH_URL=https://ojsdef.id
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
    restart: always
    networks:
      - ojsdef_net

  # ── Backend API ────────────────────────────────
  fastapi-backend:
    build:
      context: ./backend
      dockerfile: Dockerfile.prod
    environment:
      - DATABASE_URL=postgresql+asyncpg://ojsdef:${DB_PASSWORD}@postgres:5432/ojsdef
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET=${JWT_SECRET}
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
      - MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
      - SENTRY_DSN=${SENTRY_DSN}
      - CVE_API_KEY=${CVE_API_KEY}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: always
    networks:
      - ojsdef_net

  # ── Celery Beat (Scheduler) ────────────────────
  celery-beat:
    build:
      context: ./backend
    command: celery -A app.celery_app beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    environment: *backend-env
    depends_on:
      - redis
      - postgres
    restart: always
    networks:
      - ojsdef_net

  # ── Celery Workers ─────────────────────────────
  worker-internal:
    build:
      context: ./backend
    command: celery -A app.celery_app worker -Q internal_scan --concurrency=4 --loglevel=info -n worker-internal@%h
    environment: *backend-env
    depends_on:
      - redis
      - postgres
    restart: always
    networks:
      - ojsdef_net

  worker-external:
    build:
      context: ./backend
    command: celery -A app.celery_app worker -Q external_scan --concurrency=2 --loglevel=info -n worker-external@%h
    environment: *backend-env
    depends_on:
      - redis
      - postgres
    restart: always
    networks:
      - ojsdef_net

  worker-scoring:
    build:
      context: ./backend
    command: celery -A app.celery_app worker -Q scoring --concurrency=2 --loglevel=info -n worker-scoring@%h
    environment: *backend-env
    depends_on:
      - redis
      - postgres
      - minio
    restart: always
    networks:
      - ojsdef_net

  worker-notify:
    build:
      context: ./backend
    command: celery -A app.celery_app worker -Q notifications --concurrency=4 --loglevel=info -n worker-notify@%h
    environment: *backend-env
    depends_on:
      - redis
    restart: always
    networks:
      - ojsdef_net

  # ── Database ───────────────────────────────────
  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=ojsdef
      - POSTGRES_USER=ojsdef
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend/migrations/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ojsdef"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always
    networks:
      - ojsdef_net

  redis:
    image: redis:7-alpine
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always
    networks:
      - ojsdef_net

  # ── Object Storage ─────────────────────────────
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=${MINIO_ACCESS_KEY}
      - MINIO_ROOT_PASSWORD=${MINIO_SECRET_KEY}
    volumes:
      - minio_data:/data
    restart: always
    networks:
      - ojsdef_net

  # ── Monitoring ─────────────────────────────────
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    restart: always
    networks:
      - ojsdef_net

  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
    depends_on:
      - prometheus
    restart: always
    networks:
      - ojsdef_net

  flower:
    image: mher/flower:2.0
    command: celery --broker=redis://redis:6379/0 flower --port=5555
    environment:
      - FLOWER_BASIC_AUTH=${FLOWER_USER}:${FLOWER_PASSWORD}
    depends_on:
      - redis
    restart: always
    networks:
      - ojsdef_net

networks:
  ojsdef_net:
    driver: bridge

volumes:
  postgres_data:
  redis_data:
  minio_data:
  nginx_certs:
  nginx_webroot:
  grafana_data:
```

### 10.3 Struktur Direktori Project

```
ojsdef/
├── frontend/                   # Next.js 14 App
│   ├── app/
│   │   ├── (auth)/
│   │   │   ├── login/
│   │   │   └── register/
│   │   ├── (dashboard)/
│   │   │   ├── dashboard/
│   │   │   ├── targets/
│   │   │   │   └── [id]/
│   │   │   ├── scans/
│   │   │   │   └── [id]/
│   │   │   ├── reports/
│   │   │   └── settings/
│   │   └── admin/              # SaaS Admin panel
│   ├── components/
│   │   ├── ui/                 # shadcn/ui components
│   │   ├── dashboard/
│   │   │   ├── SecurityScoreCard.tsx
│   │   │   ├── VulnSummaryChart.tsx
│   │   │   ├── AttackSurfaceMap.tsx
│   │   │   └── ActionPlanList.tsx
│   │   ├── scans/
│   │   │   ├── ScanProgress.tsx
│   │   │   ├── FindingCard.tsx
│   │   │   └── FindingTable.tsx
│   │   └── targets/
│   ├── lib/
│   │   ├── api.ts              # Axios instance
│   │   ├── store.ts            # Zustand stores
│   │   └── utils.ts
│   ├── hooks/
│   │   ├── useScans.ts
│   │   └── useTargets.ts
│   └── Dockerfile.prod
│
├── backend/                    # Python FastAPI
│   ├── app/
│   │   ├── main.py             # FastAPI app init
│   │   ├── celery_app.py       # Celery configuration
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── targets.py
│   │   │   │   ├── scans.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── schedules.py
│   │   │   │   └── dashboard.py
│   │   │   └── plugin/
│   │   │       └── callback.py
│   │   ├── core/
│   │   │   ├── config.py       # Settings (pydantic-settings)
│   │   │   ├── security.py     # JWT, password hashing
│   │   │   ├── database.py     # SQLAlchemy async engine
│   │   │   └── middleware.py   # Auth + tenant middleware
│   │   ├── models/
│   │   │   ├── tenant.py
│   │   │   ├── user.py
│   │   │   ├── target.py
│   │   │   ├── scan_job.py
│   │   │   ├── scan_finding.py
│   │   │   └── ...
│   │   ├── schemas/            # Pydantic v2 schemas
│   │   ├── tasks/              # Celery task definitions
│   │   │   ├── internal_scan.py
│   │   │   ├── external_scan.py
│   │   │   ├── scoring.py
│   │   │   ├── notify.py
│   │   │   └── report_gen.py
│   │   ├── scanners/
│   │   │   ├── internal/
│   │   │   │   ├── config_scanner.py
│   │   │   │   ├── plugin_auditor.py
│   │   │   │   ├── rbac_auditor.py
│   │   │   │   ├── file_integrity.py
│   │   │   │   ├── content_detector.py
│   │   │   │   └── db_security.py
│   │   │   ├── external/
│   │   │   │   ├── fingerprinter.py
│   │   │   │   ├── ssl_analyzer.py
│   │   │   │   ├── header_checker.py
│   │   │   │   ├── vuln_prober.py
│   │   │   │   ├── open_dir_detector.py
│   │   │   │   └── cve_matcher.py
│   │   │   └── scoring_engine.py
│   │   └── templates/
│   │       └── reports/        # Jinja2 PDF templates
│   ├── migrations/             # Alembic migrations
│   ├── requirements.txt
│   └── Dockerfile.prod
│
├── ojs-plugin/                 # PHP OJS Plugin
│   ├── OJSDefPlugin.php
│   ├── scanners/
│   │   ├── ConfigScanner.php
│   │   ├── FileIntegrityScanner.php
│   │   ├── RBACScanner.php
│   │   └── ContentScanner.php
│   ├── classes/
│   │   └── APIClient.php       # HMAC-signed HTTP client
│   └── plugin.json
│
├── nginx/
│   ├── nginx.conf
│   └── conf.d/
│       └── ojsdef.conf
│
├── monitoring/
│   ├── prometheus.yml
│   └── grafana/
│
├── docker-compose.yml
├── docker-compose.dev.yml
└── .env.example
```

---

## 11. Keamanan Sistem

### 11.1 Security Architecture

```mermaid
flowchart TD
    A[Client Request] --> B{Nginx Rate Limit}
    B -->|Rate exceeded| C[429 Too Many Requests]
    B -->|OK| D{HTTPS/TLS 1.3?}
    D -->|No| E[Redirect to HTTPS]
    D -->|Yes| F{JWT Valid?}
    F -->|Invalid/Expired| G[401 Unauthorized]
    F -->|Valid| H{Role Check RBAC}
    H -->|Insufficient role| I[403 Forbidden]
    H -->|OK| J{Tenant ID Match?}
    J -->|Mismatch| K[403 Forbidden]
    J -->|OK| L{Input Validation\nPydantic v2}
    L -->|Invalid schema| M[422 Unprocessable]
    L -->|Valid| N[Business Logic]
    N --> O{PostgreSQL RLS}
    O --> P[Return Data]

    style C fill:#DC2626,color:#fff
    style G fill:#DC2626,color:#fff
    style I fill:#DC2626,color:#fff
    style K fill:#DC2626,color:#fff
    style M fill:#DC2626,color:#fff
    style P fill:#22C55E,color:#fff
```

### 11.2 Plugin Communication Security

```mermaid
sequenceDiagram
    participant PHP as OJS Plugin (PHP)
    participant API as FastAPI

    note over PHP,API: Setiap request plugin ke API menggunakan HMAC-SHA256

    PHP->>PHP: Compose request body (JSON)
    PHP->>PHP: timestamp = time()
    PHP->>PHP: message = target_id + ":" + timestamp + ":" + body_hash
    PHP->>PHP: signature = HMAC-SHA256(api_key, message)
    PHP->>API: POST /plugin/v1/callback\nHeaders: X-Signature, X-Target-ID, X-Timestamp

    API->>API: Check |timestamp - now()| <= 300s (replay attack prevention)
    API->>API: Fetch api_key dari DB untuk target_id
    API->>API: Recompute expected_signature
    API->>API: Compare signatures (constant-time)

    alt Signature valid
        API->>API: Process audit data
        API-->>PHP: 202 Accepted
    else Signature invalid
        API-->>PHP: 401 Unauthorized
    end
```

### 11.3 Security Controls Summary

| Layer | Control | Implementasi |
|---|---|---|
| **Transport** | TLS 1.3 minimum | Nginx + Let's Encrypt; HSTS header |
| **Authentication** | JWT Bearer + Refresh Token | `python-jose`; httpOnly cookie di frontend |
| **Authorization** | RBAC + Tenant Isolation | FastAPI middleware + PostgreSQL RLS |
| **Plugin Auth** | HMAC-SHA256 + Timestamp | Replay prevention (5 menit window) |
| **Input** | Schema validation | Pydantic v2 di setiap endpoint |
| **API Security** | Rate limiting | Nginx limit_req_zone; per-tenant quota |
| **Data at rest** | Column encryption | AES-256-GCM untuk `plugin_api_key` |
| **Password** | Bcrypt hashing | `passlib[bcrypt]`; cost factor 12 |
| **Scan target** | Domain ownership | Verifikasi sebelum scan pertama |
| **Audit trail** | Log semua aksi | `audit_logs` tabel dengan metadata |
| **Secret management** | Environment variables | Docker secrets / `.env` tidak di-commit |
| **Dependencies** | Vulnerability scanning | Dependabot; `pip-audit` di CI/CD |

---

## 12. Pengujian & Kriteria Penerimaan

### 12.1 Strategi Pengujian

```mermaid
graph TB
    subgraph UNIT["Unit Tests (pytest)"]
        U1["Scanner Module Tests"]
        U2["CVSS Scoring Tests"]
        U3["HMAC Validation Tests"]
        U4["Pydantic Schema Tests"]
    end

    subgraph INT["Integration Tests"]
        I1["API Endpoint Tests (pytest + httpx)"]
        I2["Database Query Tests"]
        I3["Celery Task Tests"]
        I4["Plugin Callback Tests"]
    end

    subgraph E2E["End-to-End Tests (Playwright)"]
        E1["User Registration + Login Flow"]
        E2["Target Add + Verify Flow"]
        E3["Scan Execution + Results Flow"]
        E4["Report Download Flow"]
    end

    subgraph PERF["Performance Tests (Locust)"]
        P1["API Load Test\n100 concurrent users"]
        P2["Concurrent Scan Test\n20 simultaneous scans"]
        P3["Dashboard Load Test\nLighthouse P95"]
    end

    subgraph SEC["Security Tests"]
        S1["OWASP ZAP Scan pada API"]
        S2["JWT Bypass Attempts"]
        S3["SQL Injection via API Params"]
        S4["Rate Limit Verification"]
    end

    UNIT --> INT
    INT --> E2E
    E2E --> PERF
    E2E --> SEC
```

### 12.2 Kriteria Penerimaan Utama

| # | Test Case | Input | Expected Output | Pass Criteria |
|---|---|---|---|---|
| TC-01 | Login valid | Email + password benar | `access_token` + `refresh_token` | HTTP 200, token valid JWT |
| TC-02 | Login invalid password | Email benar, password salah | Error message | HTTP 401, tidak expose info email/password mana yang salah |
| TC-03 | Akses endpoint tanpa token | Request tanpa Authorization header | Error | HTTP 401 |
| TC-04 | RBAC: `admin_ojs` akses saas_admin endpoint | Token admin_ojs | Forbidden | HTTP 403 |
| TC-05 | Tambah target valid | URL HTTPS + nama | Target tersimpan | HTTP 201, `is_verified: false` |
| TC-06 | Tambah target duplikat | URL yang sudah ada di tenant | Error | HTTP 409 Conflict |
| TC-07 | Scan tanpa verifikasi | Target `is_verified: false` | Error | HTTP 400, pesan: "Domain belum diverifikasi" |
| TC-08 | Scan full berhasil | Target verified + plugin connected | Scan selesai dengan findings | Status `completed`, `overall_score` 0–100 |
| TC-09 | Internal scan deteksi content injection | Plugin data dengan URL judi | Finding terdeteksi | Finding dengan `severity: critical`, `finding_type: content_injection` |
| TC-10 | External scan SSL expired | Target dengan SSL expired | Finding terdeteksi | Finding dengan `severity: critical`, `finding_type: ssl_expired` |
| TC-11 | Risk score critical | 1+ temuan Critical | Score rendah + notifikasi | `risk_level: critical`, notifikasi email/Telegram terkirim dalam 5 menit |
| TC-12 | PDF report | Scan completed | PDF ter-generate | File tersedia di MinIO, URL dapat diakses |
| TC-13 | Multi-tenant isolation | User tenant A akses data tenant B | Forbidden | HTTP 404 (data tidak ditemukan, bukan 403 — tidak leak existence) |
| TC-14 | Plugin HMAC invalid | Request dengan signature salah | Error | HTTP 401 |
| TC-15 | Rate limiting | > 100 req/menit dari 1 IP | Throttled | HTTP 429 |

---

## 13. Batasan & Risiko Teknis

### 13.1 Risiko Teknis & Mitigasi

| ID | Risiko | Probabilitas | Dampak | Mitigasi |
|---|---|---|---|---|
| R-01 | External Bot menyebabkan DoS tidak sengaja ke target | Sedang | Tinggi | Rate limit ketat (10 req/s); delay antar request; mode "gentle scan" default; monitoring request count |
| R-02 | Plugin dijadikan backdoor oleh pihak ketiga | Rendah | Kritis | Plugin hanya terima request dari IP OJSDef; HMAC signing wajib; code audit berkala; plugin open-source |
| R-03 | Data scan klien bocor (breach di OJSDef) | Rendah | Kritis | Enkripsi AES-256 data sensitif; RLS PostgreSQL; pentest rutin pada platform OJSDef |
| R-04 | False positive tinggi → alarm fatigue | Tinggi | Sedang | Validasi multi-layer; mekanisme "mark as false positive"; user feedback loop; threshold tuning |
| R-05 | Unauthorized scanning (scan domain orang lain) | Sedang | Tinggi | Verifikasi kepemilikan domain wajib; TOS ketat; audit log semua aktivitas scan |
| R-06 | CVE database tidak update → kerentanan baru tidak terdeteksi | Sedang | Sedang | Daily scheduled sync NVD API; alerting jika sync gagal > 48 jam |
| R-07 | Plugin tidak kompatibel dengan beberapa versi OJS/PHP | Tinggi | Sedang | Test matrix OJS 3.3.x + 3.4.x × PHP 7.4/8.0/8.1/8.2; graceful fallback jika fungsi tidak tersedia |
| R-08 | NVD API rate limit terlampaui | Sedang | Rendah | Cache CVE data di Redis; batch request; exponential backoff retry |

### 13.2 Out of Scope

Fitur-fitur berikut **tidak** termasuk dalam lingkup pengembangan OJSDef v1.0:

- Penetration testing aktif/destruktif (hanya passive scan)
- Scanning platform CMS selain OJS (WordPress, Drupal, dll)
- Perbaikan/patching otomatis pada server target tanpa konfirmasi eksplisit
- Aplikasi mobile native (Android/iOS) — web-only di fase awal
- OJS versi 2.x (End of Life)
- Monitoring performa server (CPU, RAM, disk) — bukan fokus keamanan
- Layanan konsultasi keamanan langsung oleh manusia

---

## 14. Glosarium

| Istilah | Definisi |
|---|---|
| **Attack Surface** | Keseluruhan titik (endpoint, interface, file) yang berpotensi dieksploitasi penyerang |
| **Attack Surface Mapping** | Proses mengidentifikasi dan memetakan semua komponen sistem yang dapat menjadi vektor serangan |
| **Bcrypt** | Algoritma hashing password yang secara by-design lambat, tahan terhadap brute force |
| **Celery Beat** | Komponen Celery yang bertugas sebagai scheduler — menjalankan task secara periodik (cron-like) |
| **Content Injection** | Penyisipan konten tidak sah (iklan judi, malware, spam) ke dalam konten website |
| **CVSS v3** | Standar penilaian keparahan kerentanan keamanan dengan skala 0.0–10.0 dari FIRST.org |
| **CVE** | Penomoran standar untuk kerentanan keamanan yang diketahui publik (misal: CVE-2024-12345) |
| **Defacement** | Serangan yang mengubah tampilan halaman website secara tidak sah |
| **False Positive** | Kondisi di mana sistem melaporkan kerentanan yang sebenarnya tidak ada |
| **File Integrity Check** | Verifikasi file sistem tidak berubah dengan membandingkan hash (SHA-256) |
| **HMAC-SHA256** | Hash-based Message Authentication Code menggunakan SHA-256 untuk verifikasi integritas dan autentikasi pesan |
| **JWT** | JSON Web Token — token terenkripsi untuk autentikasi stateless |
| **MinIO** | Object storage S3-compatible yang dapat dijalankan secara self-hosted |
| **Multi-tenant** | Arsitektur di mana satu instance aplikasi melayani banyak pelanggan (tenant) secara terisolasi |
| **NVD** | National Vulnerability Database — database resmi CVE dari NIST (nvd.nist.gov) |
| **OWASP Top 10** | Daftar 10 kerentanan keamanan aplikasi web paling kritis menurut OWASP |
| **Passive Scan** | Pemindaian yang hanya membaca/mengobservasi tanpa mengirim payload berbahaya |
| **RBAC** | Role-Based Access Control — pembatasan akses berdasarkan peran pengguna |
| **RLS** | Row-Level Security — fitur PostgreSQL untuk memfilter baris data berdasarkan konteks sesi |
| **SaaS** | Software as a Service — model software berbasis cloud, diakses melalui browser |
| **Tenant** | Institusi/organisasi pengguna dalam sistem multi-tenant |
| **WeasyPrint** | Library Python untuk konversi HTML/CSS menjadi PDF |

---

*Dokumen ini merupakan bagian dari deliverable Capstone Project Kelompok 3 — Topik G2, Fakultas Ilmu Komputer, Universitas Brawijaya, 2026. Dilarang mendistribusikan tanpa izin tertulis dari tim pengembang dan mitra Seclab Indonesia.*
