-- =============================================================
-- OJSDef — PostgreSQL DDL Schema
-- Berdasarkan SRS OJSDef v1.0, Bagian 4 (Desain Database)
-- =============================================================

-- Mengaktifkan ekstensi untuk UUID v4
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================
-- ENUM TYPES
-- =============================================================

CREATE TYPE tenant_plan AS ENUM ('free', 'pro', 'enterprise');
CREATE TYPE user_role AS ENUM ('admin_OJS', 'admin_SaaS');
CREATE TYPE scan_type AS ENUM ('internal', 'external', 'full');
CREATE TYPE scan_status AS ENUM ('queued', 'running', 'completed', 'failed');
CREATE TYPE risk_level AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE finding_category AS ENUM ('internal', 'external');
CREATE TYPE finding_severity AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE report_format AS ENUM ('pdf', 'json', 'html');
CREATE TYPE notification_channel AS ENUM ('email', 'telegram');
CREATE TYPE notification_type AS ENUM ('critical_alert', 'scan_summary');

-- =============================================================
-- TABEL: tenants
-- =============================================================
CREATE TABLE tenants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL UNIQUE,
    plan            tenant_plan NOT NULL DEFAULT 'free',
    api_quota       INT NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- TABEL: users
-- =============================================================
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email               VARCHAR(255) NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    full_name           VARCHAR(255) NOT NULL,
    role                user_role NOT NULL DEFAULT 'admin_OJS',
    is_active           BOOLEAN NOT NULL DEFAULT true,
    notif_email         BOOLEAN NOT NULL DEFAULT true,
    notif_telegram      BOOLEAN NOT NULL DEFAULT false,
    telegram_chat_id    VARCHAR(255),
    last_login          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- TABEL: ojs_targets
-- =============================================================
CREATE TABLE ojs_targets (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_by          UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    url                 VARCHAR(2048) NOT NULL UNIQUE,
    name                VARCHAR(255) NOT NULL,
    verification_token  VARCHAR(255),
    is_verified         BOOLEAN NOT NULL DEFAULT false,
    plugin_api_key      TEXT,                    -- encrypted at app layer
    plugin_connected    BOOLEAN NOT NULL DEFAULT false,
    ojs_version         VARCHAR(50),
    plugin_last_seen    TIMESTAMPTZ,
    last_scan_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- TABEL: scan_jobs
-- =============================================================
CREATE TABLE scan_jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_id           UUID NOT NULL REFERENCES ojs_targets(id) ON DELETE CASCADE,
    initiated_by        UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    scan_type           scan_type NOT NULL,
    status              scan_status NOT NULL DEFAULT 'queued',
    celery_task_id      VARCHAR(255),
    overall_score       DECIMAL(5, 2),           -- 0.00 - 100.00
    risk_level          risk_level,
    total_findings      INT NOT NULL DEFAULT 0,
    critical_count      INT NOT NULL DEFAULT 0,
    high_count          INT NOT NULL DEFAULT 0,
    medium_count        INT NOT NULL DEFAULT 0,
    low_count           INT NOT NULL DEFAULT 0,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================
-- TABEL: scan_findings
-- =============================================================
CREATE TABLE scan_findings (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id              UUID NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
    finding_type        VARCHAR(255) NOT NULL,
    category            finding_category NOT NULL,
    severity            finding_severity NOT NULL,
    cvss_score          DECIMAL(4, 2),           -- 0.0 - 10.0
    cve_id              VARCHAR(50),
    owasp_category      VARCHAR(100),
    title               VARCHAR(500) NOT NULL,
    description         TEXT NOT NULL,
    affected_path       TEXT,
    evidence            TEXT,
    remediation         TEXT,
    is_false_positive   BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- =============================================================
-- TABEL: reports
-- =============================================================
CREATE TABLE reports (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id              UUID NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
    format              report_format NOT NULL,
    file_url            TEXT NOT NULL,            -- MinIO object path
    file_size_bytes     INT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at          TIMESTAMPTZ
);

-- =============================================================
-- TABEL: notifications
-- =============================================================
CREATE TABLE notifications (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id              UUID NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel             notification_channel NOT NULL,
    type                notification_type NOT NULL,
    payload             JSONB,
    is_sent             BOOLEAN NOT NULL DEFAULT false,
    sent_at             TIMESTAMPTZ,
    error_log           TEXT
);

-- =============================================================
-- TABEL: audit_logs
-- =============================================================
CREATE TABLE audit_logs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    action              VARCHAR(100) NOT NULL,
    resource_type       VARCHAR(100),
    resource_id         UUID,
    ip_address          INET,
    user_agent          TEXT,
    metadata            JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- =============================================================
-- INDEXES (SRS Bagian 4.3 — Indexing Strategy)
-- =============================================================

-- Tenant & User indexes
CREATE INDEX idx_tenants_slug ON tenants(slug);
CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);

-- OJS Targets indexes
CREATE INDEX idx_ojs_targets_tenant_id ON ojs_targets(tenant_id);
CREATE INDEX idx_ojs_targets_created_by ON ojs_targets(created_by);

-- Scan Jobs indexes
CREATE INDEX idx_scan_jobs_target_id ON scan_jobs(target_id);
CREATE INDEX idx_scan_jobs_status ON scan_jobs(status);
CREATE INDEX idx_scan_jobs_initiated_by ON scan_jobs(initiated_by);

-- Partial index for active/running jobs (optimisasi query scan yg sedang berjalan)
CREATE INDEX idx_scan_jobs_active ON scan_jobs(target_id, created_at)
    WHERE status IN ('queued', 'running');

-- Scan Findings indexes
CREATE INDEX idx_scan_findings_job_id ON scan_findings(job_id);
CREATE INDEX idx_scan_findings_severity ON scan_findings(severity);

-- Full-text search for findings (title + description)
CREATE INDEX idx_findings_title_fts ON scan_findings
    USING gin(to_tsvector('english', title || ' ' || description));


-- Reports indexes
CREATE INDEX idx_reports_job_id ON reports(job_id);

-- Notifications indexes
CREATE INDEX idx_notifications_job_id ON notifications(job_id);
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
CREATE INDEX idx_notifications_unsent ON notifications(job_id)
    WHERE is_sent = false;

-- Audit Logs indexes
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);


-- =============================================================
-- ROW-LEVEL SECURITY (SRS Bagian 4.2 — Multi-Tenancy RLS)
-- =============================================================

-- Aktifkan RLS pada tabel-tabel yang memiliki tenant_id
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE ojs_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Policy isolasi tenant: user hanya bisa akses data milik tenant-nya
CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY tenant_isolation_ojs_targets ON ojs_targets
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
