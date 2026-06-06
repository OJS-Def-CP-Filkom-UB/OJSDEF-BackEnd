# Design Spec: RBAC & Multi-Tenancy Fix

**Date**: 2026-06-06
**Status**: Awaiting Review
**Scope**: `OJSDEF-BackEnd` — seluruh lapisan isolasi tenant
**Approach**: Big Bang — semua perubahan naik sekaligus dalam satu deployment ke VPS

---

## 1. Latar Belakang & Motivasi

Ditemukan bahwa data antar-tenant (institusi) tercampur: user `admin_ojs` dari institusi A bisa melihat target OJS, scan, temuan, dan laporan milik institusi B. Setelah analisis mendalam ditemukan **6 bug berlapis** yang semuanya harus diperbaiki bersamaan.

Platform sudah dalam fase MVP aktif dengan data nyata mulai dikumpulkan, sehingga perbaikan ini bersifat kritis sebelum data semakin bertambah.

---

## 2. Temuan Bug

### Bug #1 — Root Cause: `FORCE ROW LEVEL SECURITY` Tidak Ada
**File**: `migrations/versions/001_initial.py`

Migration menggunakan `ENABLE ROW LEVEL SECURITY` tanpa `FORCE ROW LEVEL SECURITY`. Di PostgreSQL, table owner (user yang menjalankan Alembic) secara otomatis **bypass RLS** kecuali `FORCE` ditambahkan. Karena `DATABASE_URL` menggunakan user pemilik tabel, seluruh RLS tidak pernah aktif sejak awal.

Selain itu, fallback kondisi `OR current_setting('app.current_tenant_id', true) = ''` salah logika: saat setting tidak di-set, `current_setting(..., true)` mengembalikan `NULL`, bukan string kosong. `NULL = ''` → `NULL` (falsy), bukan `true`.

### Bug #2 — Semua Router Tidak Memfilter `tenant_id`
**Files**: `routers/targets.py`, `routers/scans.py`, `routers/reports.py`

Tidak ada satu pun query `SELECT` / `DELETE` yang menambahkan `WHERE tenant_id = X`. Seluruh isolasi diserahkan ke RLS yang tidak aktif (Bug #1). Contoh:
- `list_targets`: `select(OJSTarget)` — tanpa filter
- `get_target`: bisa akses target tenant lain via UUID
- `start_scan`: bisa mulai scan di target tenant lain
- `list_reports`: semua laporan semua tenant terlihat

### Bug #3 — `dashboard.py` `_build_stats` Abaikan `tenant_id`
**File**: `routers/dashboard.py`

Fungsi `_build_stats(db, tenant_id)` menerima `tenant_id` sebagai parameter tetapi tidak menggunakannya di satu pun query. Semua statistik dashboard adalah agregasi lintas semua tenant.

### Bug #4 — `SET LOCAL` Hilang Setelah `commit()`
**File**: `database.py`

`SET LOCAL` hanya berlaku dalam satu transaksi. Setiap kali `await session.commit()` dipanggil (misalnya di `create_target()`, `create_audit_log()`), transaksi berakhir dan tenant context hilang. Query setelah commit berjalan tanpa isolasi.

### Bug #5 — `plugin_callback.py` Bypass Tenant Context
**File**: `routers/plugin_callback.py`

`_probe_plugin`, `plugin_heartbeat`, `plugin_callback` membuat `AsyncSessionLocal()` langsung tanpa set tenant context. Dengan RLS aktif, semua query di sini akan diblokir karena tidak ada `app.current_tenant_id` yang di-set.

### Bug #6 — `saas_admin` Tidak Punya Mekanisme Cross-Tenant
**File**: `routers/admin.py`, `database.py`

`saas_admin` butuh akses ke semua tenant (list users, audit logs, dsb.), namun tidak ada mekanisme untuk membebaskannya dari filter tenant. Dengan RLS aktif, `saas_admin` pun akan terisolasi ke tenant-nya sendiri saja.

---

## 3. Keputusan Desain

| Topik | Keputusan |
|-------|-----------|
| Strategi perbaikan | Dua lapisan: RLS database + explicit `tenant_id` filter di aplikasi |
| Bypass `saas_admin` | RLS policy exception via `app.current_role = 'saas_admin'` |
| Plugin tenant context | Explicit filter + `set_tenant_context` dari `request.state.plugin_target.tenant_id` |
| `SET LOCAL` → `SET` | Ganti ke session-level `SET`, reset ke `''` saat session ditutup |
| Migration strategy | Migration baru 005 — tidak modifikasi migration lama |
| Deployment strategy | Big Bang — semua perubahan naik sekaligus ke VPS |

---

## 4. Desain: Lapisan Database (Migration 005)

### File
`migrations/versions/005_rbac_tenancy_fix.py`

### Langkah-langkah

**Step 1 — Buat PostgreSQL role `ojsdef_app`**
```sql
CREATE ROLE ojsdef_app WITH LOGIN PASSWORD '<password>';
```
Role ini adalah **non-owner** — dikenai RLS secara penuh. Dipakai oleh koneksi runtime FastAPI.

**Step 2 — Grant privileges ke `ojsdef_app`**
```sql
GRANT USAGE ON SCHEMA public TO ojsdef_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ojsdef_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ojsdef_app;
```

**Step 3 — Aktifkan `FORCE ROW LEVEL SECURITY`**
```sql
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
```
Berlaku untuk semua tabel di `RLS_TABLES`: `users`, `ojs_targets`, `scan_jobs`, `scan_findings`, `scan_schedules`, `reports`, `notifications`, `audit_logs`.

**Step 4 — Drop policy lama, buat policy baru**

Policy lama dihapus:
```sql
DROP POLICY IF EXISTS tenant_isolation ON {table};
```

Policy baru dengan dua kondisi:
```sql
CREATE POLICY tenant_isolation ON {table}
USING (
    current_setting('app.current_role', true) = 'saas_admin'
    OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
);
```

**Logika policy:**
- Jika `app.current_role = 'saas_admin'` → semua baris terlihat (cross-tenant access)
- Jika `app.current_tenant_id` di-set ke UUID valid → hanya baris dengan `tenant_id` yang cocok
- Jika tidak ada context sama sekali → casting `NULL::uuid` menghasilkan `NULL`, `tenant_id = NULL` adalah `NULL` (falsy) — semua baris diblokir (fail-safe)

### Downgrade
Drop `FORCE ROW LEVEL SECURITY`, drop policy baru, recreate policy lama, drop role `ojsdef_app`.

### `.env` Update
```env
# Lama — tetap dipakai untuk Alembic migration (butuh privilege DDL)
DATABASE_URL=postgresql+asyncpg://ojsdef:<password>@host:5432/ojsdef

# Baru — dipakai oleh FastAPI runtime (non-owner, kena RLS)
DATABASE_URL_APP=postgresql+asyncpg://ojsdef_app:<password>@host:5432/ojsdef
```

---

## 5. Desain: `database.py`

### Perubahan

**Engine runtime menggunakan `DATABASE_URL_APP`**:
```python
engine = create_async_engine(settings.database_url_app, ...)
```

**`set_tenant_context` — ganti `SET LOCAL` ke `SET`, tambah parameter `role`**:
```python
async def set_tenant_context(session: AsyncSession, tenant_id: str, role: str) -> None:
    _uuid.UUID(tenant_id)  # validasi format UUID
    await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))
    await session.execute(text(f"SET app.current_role = '{role}'"))
```

`SET` (tanpa `LOCAL`) berlaku di level session/koneksi — tidak hilang setelah `commit()`.

**`get_db` — inject role + reset di akhir**:
```python
async def get_db(request: Request):
    async with AsyncSessionLocal() as session:
        tenant_id = getattr(request.state, "tenant_id", None)
        role = getattr(request.state, "role", None)
        if tenant_id and role:
            await set_tenant_context(session, tenant_id, role)
        try:
            yield session
        finally:
            # Reset context sebelum koneksi dikembalikan ke pool
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.current_role = ''"))
```

Reset di `finally` memastikan koneksi yang dikembalikan ke pool tidak membawa tenant context dari request sebelumnya.

**`make_worker_session` — tidak berubah** (Celery worker pakai `DATABASE_URL` owner, akses semua data secara legitimate untuk keperluan scoring/notifikasi).

---

## 6. Desain: `config.py`

Tambahkan field `database_url_app`:
```python
class Settings(BaseSettings):
    database_url: str       # Alembic migration (DDL privileges)
    database_url_app: str   # FastAPI runtime (ojsdef_app role, kena RLS)
    ...
```

---

## 7. Desain: `middleware/auth.py`

Tidak ada perubahan struktural. `request.state.role` sudah di-set di middleware yang ada dan akan dibaca oleh `get_db` secara otomatis.

---

## 8. Desain: Router Changes

Semua endpoint list/get/delete menambahkan explicit `WHERE tenant_id = X` sebagai defense-in-depth di atas RLS.

### 8.1 `routers/targets.py`

**`list_targets`**:
```python
tid = uuid.UUID(current["tenant_id"])
result = await db.execute(select(OJSTarget).where(OJSTarget.tenant_id == tid))
```

**`get_target`**, **`delete_target`**, **`verify_target`**, **`plugin_guide`**, **`regen_key`**:
```python
result = await db.execute(
    select(OJSTarget).where(
        OJSTarget.id == target_id,
        OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
    )
)
```
Jika target tidak ditemukan (karena beda tenant), tetap kembalikan 404 — tidak bocorkan informasi apakah resource ada.

### 8.2 `routers/scans.py`

**`list_scans`**:
```python
tid = uuid.UUID(current["tenant_id"])
q = select(ScanJob).where(ScanJob.tenant_id == tid).order_by(...).limit(limit)
```

**`get_scan`**:
```python
result = await db.execute(
    select(ScanJob).where(
        ScanJob.id == job_id,
        ScanJob.tenant_id == uuid.UUID(current["tenant_id"]),
    )
)
```

**`start_scan`** — verifikasi target milik tenant yang sama:
```python
result = await db.execute(
    select(OJSTarget).where(
        OJSTarget.id == body.target_id,
        OJSTarget.tenant_id == uuid.UUID(current["tenant_id"]),
    )
)
```

**`get_findings`** — verifikasi job ownership dulu, baru query findings:
```python
# Step 1: pastikan job milik tenant ini
job_result = await db.execute(
    select(ScanJob).where(
        ScanJob.id == job_id,
        ScanJob.tenant_id == uuid.UUID(current["tenant_id"]),
    )
)
if not job_result.scalar_one_or_none():
    raise HTTPException(404, "Scan tidak ditemukan")
# Step 2: baru query findings (findings inherit tenant dari job-nya)
q = select(ScanFinding).where(ScanFinding.job_id == job_id)
```

**`mark_false_positive`** — verifikasi job ownership sebelum update finding.

### 8.3 `routers/reports.py`

**`list_reports`**:
```python
tid = uuid.UUID(current["tenant_id"])
result = await db.execute(
    select(Report).where(Report.tenant_id == tid).order_by(Report.created_at.desc())
)
```

**`download_pdf`**, **`download_json`**:
```python
result = await db.execute(
    select(Report).where(
        Report.id == report_id,
        Report.tenant_id == uuid.UUID(current["tenant_id"]),
    )
)
```

### 8.4 `routers/dashboard.py`

**`_build_stats`** — gunakan `tenant_id` di semua query:
```python
async def _build_stats(db: AsyncSession, tenant_id: str) -> dict:
    tid = uuid.UUID(tenant_id)

    targets_count = (await db.execute(
        select(func.count()).select_from(OJSTarget)
        .where(OJSTarget.tenant_id == tid)
    )).scalar()

    scans_result = await db.execute(
        select(ScanJob).where(
            ScanJob.tenant_id == tid,
            ScanJob.created_at >= month_ago,
        )
    )
```

### 8.5 `routers/admin.py`

Tidak ada perubahan. `saas_admin`-only endpoint dengan RLS policy exception sudah menjamin cross-tenant access yang benar. Intent memang cross-tenant untuk admin.

### 8.6 `routers/audit_logs.py`

Tidak ada perubahan. `saas_admin`-only, sudah punya filter opsional `tenant_id` via query param.

---

## 9. Desain: `plugin_callback.py`

Plugin diautentikasi HMAC oleh `plugin_auth_middleware`. Setelah middleware, `request.state.plugin_target` berisi object `OJSTarget` lengkap termasuk `tenant_id`.

### Pola yang diterapkan

Setiap fungsi yang membuat `AsyncSessionLocal()` langsung harus set tenant context sebelum query:

**`plugin_heartbeat`** dan **`plugin_callback`**:
```python
target: OJSTarget = request.state.plugin_target
tenant_id = str(target.tenant_id)

async with AsyncSessionLocal() as session:
    await set_tenant_context(session, tenant_id, "plugin")
    result = await session.execute(
        select(OJSTarget).where(OJSTarget.id == target.id)
    )
    ...
    # Reset setelah selesai
    await session.execute(text("SET app.current_tenant_id = ''"))
    await session.execute(text("SET app.current_role = ''"))
```

**`_probe_plugin`** — tambahkan `tenant_id` sebagai parameter baru:
```python
async def _probe_plugin(probe_endpoint: str, api_key: str, challenge: str,
                        target_id: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id, "plugin")
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )
        ...
```

Caller di `plugin_heartbeat` perlu meneruskan `str(target.tenant_id)` saat memanggil `_probe_plugin`.

**Catatan**: `app.current_role = 'plugin'` tidak diberi exception di RLS policy — plugin menggunakan tenant context yang valid dari HMAC auth, sehingga RLS normal berlaku dengan benar.

---

## 10. Penanganan Login Endpoint (Bug Tambahan)

Saat user login, belum ada JWT sehingga `request.state.tenant_id` tidak ada. `get_db` tidak akan set tenant context. Dengan RLS aktif via `ojsdef_app`, query `select(User).where(User.email == email)` akan diblokir RLS karena tidak ada `app.current_tenant_id`.

**Solusi**: Login endpoint menggunakan engine owner (`DATABASE_URL`) secara langsung — bukan melalui `get_db`. Buat dependency terpisah `get_auth_db` yang menggunakan `AsyncSessionLocal` berbasis engine owner:

```python
# database.py — tambahan
owner_engine = create_async_engine(settings.database_url, ...)
OwnerSessionLocal = async_sessionmaker(owner_engine, ...)

async def get_auth_db():
    """Session tanpa RLS — hanya untuk auth endpoints (login, refresh)."""
    async with OwnerSessionLocal() as session:
        yield session
```

`routers/auth.py` — endpoint `/login` dan `/refresh` menggunakan `get_auth_db` sebagai ganti `get_db`.

---

## 11. File yang Berubah

| File | Jenis Perubahan |
|------|----------------|
| `migrations/versions/005_rbac_tenancy_fix.py` | **BARU** — FORCE RLS + policy baru + role ojsdef_app |
| `app/config.py` | Tambah field `database_url_app` |
| `app/database.py` | Engine app pakai `database_url_app`; `set_tenant_context` ganti `SET LOCAL` → `SET` + inject `role`; `get_db` reset context di `finally`; tambah `get_auth_db` + `owner_engine` |
| `app/routers/auth.py` | Login & refresh pakai `get_auth_db` |
| `app/routers/targets.py` | Explicit `tenant_id` filter di semua endpoint |
| `app/routers/scans.py` | Explicit `tenant_id` filter + verifikasi ownership |
| `app/routers/reports.py` | Explicit `tenant_id` filter di semua endpoint |
| `app/routers/dashboard.py` | Gunakan `tenant_id` di semua query `_build_stats` |
| `app/routers/plugin_callback.py` | Set tenant context dari `request.state.plugin_target.tenant_id` |
| `.env.example` | Tambah `DATABASE_URL_APP` |

**Tidak berubah**: `middleware/auth.py`, `routers/admin.py`, `routers/audit_logs.py`, semua worker/scanner.

---

## 12. Prosedur Deployment ke VPS

Karena tidak ada database lokal, semua perubahan harus naik sekaligus:

1. Commit semua perubahan kode di lokal
2. Push ke VPS
3. Buat role `ojsdef_app` di PostgreSQL VPS (manual via `psql`, atau otomatis via migration jika user Alembic adalah superuser)
4. Update `.env` di VPS — tambahkan `DATABASE_URL_APP` dengan kredensial `ojsdef_app`
5. Jalankan migration: `alembic upgrade head`
6. Restart FastAPI service
7. Verifikasi: login dua user dari tenant berbeda, pastikan data tidak tercampur

**Catatan**: Pembuatan role PostgreSQL membutuhkan superuser privileges. Jika user `ojsdef` di `DATABASE_URL` bukan superuser, buat role manual via `psql` di VPS sebelum menjalankan migration.

---

## 13. Risiko & Mitigasi

| Risiko | Mitigasi |
|--------|----------|
| Migration gagal karena `CREATE ROLE` butuh superuser | Buat role manual via `psql` sebelum run migration; migration skip jika role sudah ada (`IF NOT EXISTS`) |
| `SET` session-level bocor ke request lain via pool | Reset ke `''` di `finally` block `get_db` — koneksi selalu bersih saat dikembalikan ke pool |
| Celery worker terhenti karena tidak punya tenant context | `make_worker_session` tetap pakai `DATABASE_URL` (owner) — tidak kena FORCE RLS |
| `saas_admin` kehilangan akses cross-tenant | Dijamin oleh RLS policy exception `app.current_role = 'saas_admin'` yang di-set di `get_db` |
| Login gagal karena tidak ada tenant context saat auth | Endpoint `/login` dan `/refresh` menggunakan `get_auth_db` (owner engine, tanpa RLS) |
