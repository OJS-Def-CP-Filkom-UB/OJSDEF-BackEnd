-- Mengaktifkan ekstensi untuk UUID v4
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enum untuk plan Tenant dan role User
CREATE TYPE tenant_plan AS ENUM ('free', 'pro', 'enterprise');
CREATE TYPE user_role AS ENUM ('admin_OJS', 'admin_SaaS');

-- Tabel Tenants
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    plan tenant_plan NOT NULL DEFAULT 'free',
    api_quota INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tabel Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'admin_OJS',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexing strategi (sesuai arahan dari Database Design Skill)
CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_tenants_slug ON tenants(slug);

-- ============================================================
-- Enum Types Tambahan
-- ============================================================
CREATE TYPE scan_type AS ENUM ('internal', 'external', 'full');

-- ============================================================
-- Tabel ojs_targets
-- ============================================================
CREATE TABLE ojs_targets (
    id                UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_by        UUID        NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    url               VARCHAR(2048) NOT NULL,
    name              VARCHAR(255) NOT NULL,
    verification_token TEXT        NOT NULL,
    is_verified       BOOLEAN     NOT NULL DEFAULT false,
    plugin_api_key    TEXT,                                -- dienkripsi di application layer
    is_plugin_connect BOOLEAN     NOT NULL DEFAULT false,
    ojs_version       VARCHAR(64),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index ojs_targets
CREATE INDEX idx_ojs_targets_tenant_id   ON ojs_targets(tenant_id);
CREATE INDEX idx_ojs_targets_created_by  ON ojs_targets(created_by);

-- ============================================================
-- Tabel audit_logs
-- ============================================================
CREATE TABLE audit_logs (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id       UUID        REFERENCES users(id) ON DELETE SET NULL,
    action        VARCHAR(128) NOT NULL,
    resource_type VARCHAR(128),
    resource_id   TEXT,
    ip_address    INET,
    user_agent    TEXT,
    metadata      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index audit_logs
CREATE INDEX idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX idx_audit_logs_user_id   ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action    ON audit_logs(action);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at DESC);

-- ============================================================
-- Tabel scan_schedules
-- ============================================================
CREATE TABLE scan_schedules (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_id       UUID        NOT NULL REFERENCES ojs_targets(id) ON DELETE CASCADE,
    created_by      UUID        NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    cron_expression VARCHAR(128) NOT NULL,
    scan_type       scan_type   NOT NULL DEFAULT 'full',
    is_active       BOOLEAN     NOT NULL DEFAULT true,
    next_run_at     TIMESTAMPTZ,
    last_run_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index scan_schedules
CREATE INDEX idx_scan_schedules_target_id    ON scan_schedules(target_id);
CREATE INDEX idx_scan_schedules_created_by   ON scan_schedules(created_by);
CREATE INDEX idx_scan_schedules_next_run_at  ON scan_schedules(next_run_at)
    WHERE is_active = true;

