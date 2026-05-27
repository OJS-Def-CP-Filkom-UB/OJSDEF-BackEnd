# OJSDef API — Panduan Integrasi Frontend

Dokumen ini adalah referensi lengkap untuk tim Frontend (Next.js) dalam mengintegrasikan semua endpoint backend OJSDef.

**Base URL produksi**: `https://api-ojsdef.zentaza.online`  
**Base URL development**: `http://localhost:8000`  
**API prefix**: `/api/v1` (kecuali plugin callback di `/plugin/v1`)

---

## Daftar Isi

1. [Autentikasi & Token](#1-autentikasi--token)
2. [Konvensi Umum](#2-konvensi-umum)
3. [Endpoint: Auth](#3-endpoint-auth)
4. [Endpoint: Targets (OJS Instance)](#4-endpoint-targets-ojs-instance)
5. [Endpoint: Scans](#5-endpoint-scans)
6. [Endpoint: Dashboard](#6-endpoint-dashboard)
7. [Endpoint: Reports](#7-endpoint-reports)
8. [Endpoint: Admin](#8-endpoint-admin)
9. [RBAC — Hak Akses per Role](#9-rbac--hak-akses-per-role)
10. [TypeScript Types Lengkap](#10-typescript-types-lengkap)
11. [Contoh HTTP Client Setup (Next.js)](#11-contoh-http-client-setup-nextjs)
12. [Tabel Error Codes](#12-tabel-error-codes)

---

## 1. Autentikasi & Token

Backend menggunakan **JWT Bearer Token**. Ada dua token:

| Token | TTL | Kegunaan |
|---|---|---|
| `access_token` | 1 jam | Dikirim di setiap request API sebagai `Authorization` header |
| `refresh_token` | 30 hari | Digunakan untuk memperbarui `access_token` yang expired |

### Cara kirim token di setiap request

```
Authorization: Bearer <access_token>
```

### Alur token di frontend

```
1. POST /api/v1/auth/login  →  simpan access_token + refresh_token
2. Setiap request            →  Authorization: Bearer <access_token>
3. Jika 401 Unauthorized    →  POST /api/v1/auth/refresh
4. Jika refresh gagal        →  redirect ke /login
5. POST /api/v1/auth/logout  →  hapus token dari storage
```

### Penyimpanan token yang disarankan

- `access_token` → memory (state/context), BUKAN localStorage agar tidak rentan XSS
- `refresh_token` → `httpOnly` cookie ATAU localStorage (pertimbangkan trade-off)

---

## 2. Konvensi Umum

### Format request

- Content-Type: `application/json`
- Semua ID menggunakan **UUID v4** (string)
- Semua timestamp menggunakan **ISO 8601 UTC** (`2026-05-27T10:30:00Z`)

### Format response error

Semua error mengembalikan format:
```json
{
  "detail": "Pesan error dalam Bahasa Indonesia"
}
```

### Nilai `risk_level` dan label UI

| Nilai di API | Label UI (Bahasa Indonesia) | Warna |
|---|---|---|
| `critical` | Kritis | Merah |
| `high` | Berbahaya | Oranye |
| `medium` | Perhatian | Kuning |
| `low` | Aman | Hijau |

### Nilai `status` scan job

| Nilai | Arti |
|---|---|
| `queued` | Menunggu antrian |
| `running` | Sedang berjalan |
| `completed` | Selesai |
| `failed` | Gagal |

### Nilai `scan_type`

| Nilai | Arti |
|---|---|
| `internal` | Audit via plugin PHP (konfigurasi, file integrity, plugin) |
| `external` | Scan ofensif dari luar (SSL, HTTP headers, CVE, endpoint) |
| `full` | Keduanya berjalan paralel |

---

## 3. Endpoint: Auth

### `POST /api/v1/auth/login`

Login dan dapatkan token. **Tidak butuh autentikasi.**

**Request body**:
```json
{
  "email": "admin@ojsdef.com",
  "password": "password123"
}
```

**Response `200 OK`**:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "must_change_password": false
}
```

> **Penting**: Jika `must_change_password === true`, redirect user ke halaman ganti password sebelum mengizinkan akses fitur lain.

**Errors**:
| Status | `detail` | Penyebab |
|---|---|---|
| 401 | `"Credensial tidak valid"` | Email/password salah |
| 403 | `"Akun dinonaktifkan"` | Akun diblokir admin |

---

### `POST /api/v1/auth/refresh`

Perbarui access token menggunakan refresh token. **Tidak butuh autentikasi.**

**Request body**:
```json
{
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Response `200 OK`**: sama seperti `/login`

**Errors**:
| Status | `detail` | Tindakan frontend |
|---|---|---|
| 401 | `"Refresh token tidak valid"` | Redirect ke /login |
| 401 | `"Refresh token tidak valid atau sudah digunakan"` | Redirect ke /login |
| 401 | `"User tidak ditemukan"` | Redirect ke /login |

---

### `POST /api/v1/auth/logout`

Cabut refresh token. **Butuh autentikasi.**

**Request body**:
```json
{
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Response `204 No Content`** (body kosong)

---

### `GET /api/v1/auth/me`

Ambil profil user yang sedang login. **Butuh autentikasi.**

**Response `200 OK`**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "admin@ojsdef.com",
  "full_name": "Administrator OJSDef",
  "role": "saas_admin",
  "must_change_password": false,
  "notif_email": true,
  "notif_telegram": false,
  "telegram_chat_id": null
}
```

---

### `PUT /api/v1/auth/me`

Update profil sendiri. **Butuh autentikasi.** Semua field opsional.

**Request body**:
```json
{
  "full_name": "Nama Baru",
  "notif_email": true,
  "notif_telegram": true,
  "telegram_chat_id": "123456789"
}
```

**Response `200 OK`**: sama dengan `GET /me`

---

### `PUT /api/v1/auth/change-password`

Ganti password sendiri. **Butuh autentikasi.**

**Request body**:
```json
{
  "old_password": "passwordLama123",
  "new_password": "passwordBaru456"
}
```

**Response `204 No Content`**

> Setelah ganti password, semua refresh token lain dicabut — user di device lain akan ter-logout otomatis. Frontend perlu mengarahkan user untuk login ulang setelah sukses.

**Errors**:
| Status | `detail` | Penyebab |
|---|---|---|
| 400 | `"Password lama salah"` | Verifikasi password gagal |

---

## 4. Endpoint: Targets (OJS Instance)

Semua endpoint di bagian ini **butuh autentikasi**.

### `GET /api/v1/targets`

Ambil semua target OJS milik tenant user.

**Response `200 OK`**:
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Jurnal Teknik Informatika",
    "url": "https://jti.example.ac.id",
    "is_verified": true,
    "plugin_connected": true,
    "ojs_version": "3.4.0",
    "created_at": "2026-05-01T08:00:00Z"
  },
  {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Jurnal Kesehatan",
    "url": "https://jkes.example.ac.id",
    "is_verified": false,
    "plugin_connected": false,
    "ojs_version": null,
    "created_at": "2026-05-15T10:00:00Z"
  }
]
```

> `plugin_connected`: `true` jika plugin pernah mengirim heartbeat dalam 15 menit terakhir.

---

### `POST /api/v1/targets`

Daftarkan target OJS baru.

**Request body**:
```json
{
  "name": "Jurnal Baru",
  "url": "https://jurnal-baru.example.ac.id"
}
```

**Response `201 Created`**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440003",
  "name": "Jurnal Baru",
  "url": "https://jurnal-baru.example.ac.id",
  "is_verified": false,
  "plugin_connected": false,
  "ojs_version": null,
  "created_at": "2026-05-27T11:00:00Z"
}
```

---

### `GET /api/v1/targets/{target_id}`

Ambil detail satu target.

**Path params**: `target_id` (UUID)

**Response `200 OK`**: sama dengan item di list targets

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"Target tidak ditemukan"` |

---

### `DELETE /api/v1/targets/{target_id}`

Hapus target. **Response `204 No Content`**.

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"Target tidak ditemukan"` |

---

### `POST /api/v1/targets/{target_id}/verify`

Verifikasi kepemilikan domain target. Dua metode dicoba secara berurutan:
1. **File**: GET `{url}/.well-known/ojsdef-verification.txt` berisi token
2. **DNS**: TXT record `_ojsdef-verification.{domain}` berisi token

**Response `200 OK`**:
```json
{
  "verified": true,
  "method": "file"
}
```

Jika gagal:
```json
{
  "verified": false,
  "method": null
}
```

> Frontend harus menampilkan instruksi cara menaruh token verifikasi. Token bisa didapat dari endpoint `plugin-guide` di bawah.

---

### `GET /api/v1/targets/{target_id}/plugin-guide`

Ambil API key dan instruksi pemasangan plugin.

**Response `200 OK`**:
```json
{
  "target_id": "550e8400-e29b-41d4-a716-446655440001",
  "api_key": "kunci-api-yang-sudah-didekripsi",
  "endpoint": "/plugin/v1/callback",
  "instructions": "Install plugin OJSDef di OJS, masukkan API Key dan endpoint di atas."
}
```

> Tampilkan `api_key` dengan tombol "Salin" dan peringatan agar tidak dibagikan.

---

### `POST /api/v1/targets/{target_id}/regenerate-key`

Generate API key baru untuk plugin (key lama langsung tidak valid).

**Response `200 OK`**:
```json
{
  "api_key": "api-key-baru-yang-sudah-diregenerasi"
}
```

---

## 5. Endpoint: Scans

Semua endpoint di bagian ini **butuh autentikasi**.

### `POST /api/v1/scans`

Mulai scan baru. Target **harus sudah diverifikasi** (`is_verified: true`).

**Request body**:
```json
{
  "target_id": "550e8400-e29b-41d4-a716-446655440001",
  "scan_type": "full"
}
```

**Response `201 Created`**:
```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440010",
  "target_id": "550e8400-e29b-41d4-a716-446655440001",
  "scan_type": "full",
  "status": "queued",
  "overall_score": null,
  "risk_level": null,
  "critical_count": 0,
  "high_count": 0,
  "medium_count": 0,
  "low_count": 0,
  "progress": null,
  "created_at": "2026-05-27T11:05:00Z"
}
```

**Errors**:
| Status | `detail` | Penyebab |
|---|---|---|
| 404 | `"Target tidak ditemukan"` | target_id tidak valid |
| 400 | `"Target belum diverifikasi"` | Perlu verifikasi dulu |

---

### `GET /api/v1/scans`

List semua scan job.

**Query params**:
| Param | Tipe | Default | Deskripsi |
|---|---|---|---|
| `target_id` | string (UUID) | — | Filter berdasarkan target |
| `status` | string | — | Filter berdasarkan status |
| `limit` | integer | `20` | Jumlah maksimal hasil |

**Response `200 OK`**: array of ScanJob (sama seperti `POST /scans`)

---

### `GET /api/v1/scans/{job_id}`

Detail satu scan job. Saat scan sedang berjalan, field `progress` terisi:

**Response `200 OK`**:
```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440010",
  "target_id": "550e8400-e29b-41d4-a716-446655440001",
  "scan_type": "full",
  "status": "running",
  "overall_score": null,
  "risk_level": null,
  "critical_count": 0,
  "high_count": 0,
  "medium_count": 0,
  "low_count": 0,
  "progress": {
    "stage": "external_scan",
    "current_step": 12,
    "total_steps": 50
  },
  "created_at": "2026-05-27T11:05:00Z"
}
```

> **Polling**: Frontend disarankan polling endpoint ini setiap 3–5 detik saat `status === 'running'` untuk update progres real-time.

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"Scan tidak ditemukan"` |

---

### `GET /api/v1/scans/{job_id}/findings`

Ambil semua temuan dari sebuah scan job.

**Query params**:
| Param | Tipe | Default | Deskripsi |
|---|---|---|---|
| `severity` | string | — | `critical` / `high` / `medium` / `low` |
| `category` | string | — | Filter kategori temuan |
| `page` | integer | `1` | Halaman (20 item per halaman) |

**Response `200 OK`**:
```json
[
  {
    "id": "bb0e8400-e29b-41d4-a716-446655440020",
    "finding_type": "SSL_EXPIRED",
    "category": "ssl",
    "title": "Sertifikat SSL Kedaluwarsa",
    "description": "Sertifikat SSL domain target sudah kedaluwarsa sejak 3 hari lalu.",
    "affected_path": "https://jti.example.ac.id",
    "evidence": "Certificate expiry: 2026-05-24T00:00:00Z",
    "remediation": "Perbarui sertifikat SSL menggunakan Let's Encrypt atau penyedia lainnya.",
    "severity": "critical",
    "cvss_score": 9.1,
    "cve_id": null,
    "owasp_category": "A02:2021 - Cryptographic Failures",
    "is_false_positive": false
  }
]
```

---

### `PATCH /api/v1/scans/{job_id}/findings/{finding_id}`

Toggle flag `is_false_positive` pada sebuah temuan (false → true, true → false).

**Request body**: kosong (tidak perlu body)

**Response `200 OK`**: FindingResponse (sama seperti item di list findings)

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"Finding tidak ditemukan"` |

---

## 6. Endpoint: Dashboard

**Butuh autentikasi.** Data di-cache 60 detik per tenant.

### `GET /api/v1/dashboard/stats`

Statistik ringkasan untuk halaman utama dashboard.

**Response `200 OK`**:
```json
{
  "targets": {
    "total": 5
  },
  "scans": {
    "last_30_days": 15,
    "completed": 13,
    "failed": 2
  },
  "security_posture": {
    "average_score": 72.3
  },
  "findings_summary": {
    "critical": 4,
    "high": 12
  }
}
```

| Field | Keterangan |
|---|---|
| `targets.total` | Total semua target terdaftar |
| `scans.last_30_days` | Jumlah scan dalam 30 hari terakhir |
| `security_posture.average_score` | Rata-rata skor dari scan selesai; `null` jika belum ada |
| `findings_summary` | Total temuan Kritis dan Berbahaya dari 30 hari terakhir |

---

## 7. Endpoint: Reports

Semua endpoint di bagian ini **butuh autentikasi**.

### `GET /api/v1/reports`

List semua laporan yang tersedia untuk tenant.

**Response `200 OK`**:
```json
[
  {
    "id": "cc0e8400-e29b-41d4-a716-446655440030",
    "job_id": "aa0e8400-e29b-41d4-a716-446655440010",
    "format": "pdf",
    "file_size_bytes": 258432,
    "created_at": "2026-05-27T11:30:00Z"
  },
  {
    "id": "cc0e8400-e29b-41d4-a716-446655440031",
    "job_id": "aa0e8400-e29b-41d4-a716-446655440010",
    "format": "json",
    "file_size_bytes": null,
    "created_at": "2026-05-27T11:30:01Z"
  }
]
```

---

### `GET /api/v1/reports/{report_id}/pdf`

Download laporan PDF. Response adalah **redirect `302`** ke pre-signed URL MinIO (berlaku 1 jam).

**Cara pakai di frontend**:
```typescript
// Opsi 1: buka tab baru
window.open(`/api/v1/reports/${reportId}/pdf`, '_blank')

// Opsi 2: ambil URL redirect lalu download
const res = await fetch(`/api/v1/reports/${reportId}/pdf`, {
  headers: { Authorization: `Bearer ${token}` },
  redirect: 'manual',
})
const downloadUrl = res.headers.get('location')
```

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"Laporan PDF tidak ditemukan"` |

---

### `GET /api/v1/reports/{report_id}/json`

Ambil data laporan dalam format JSON (untuk tampilan di browser).

**Response `200 OK`**:
```json
{
  "job_id": "aa0e8400-e29b-41d4-a716-446655440010",
  "scan_type": "full",
  "status": "completed",
  "overall_score": 72.3,
  "risk_level": "medium",
  "findings": [
    {
      "title": "Sertifikat SSL Kedaluwarsa",
      "severity": "critical",
      "cvss_score": 9.1,
      "description": "Sertifikat SSL domain target sudah kedaluwarsa.",
      "remediation": "Perbarui sertifikat SSL menggunakan Let's Encrypt."
    }
  ]
}
```

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"Laporan tidak ditemukan"` |

---

## 8. Endpoint: Admin

Semua endpoint di bagian ini **butuh autentikasi** dan **role `saas_admin`**. Jika role tidak sesuai, response `403 Forbidden`.

### `POST /api/v1/admin/users`

Buat user baru (biasanya `admin_ojs` atau `viewer` untuk tenant tertentu).

**Request body**:
```json
{
  "email": "manager@universitas.ac.id",
  "full_name": "Budi Santoso",
  "role": "admin_ojs",
  "tenant_id": "dd0e8400-e29b-41d4-a716-446655440040"
}
```

> `tenant_id` opsional. Jika tidak diisi, user dibuat di tenant `default`.

**Response `201 Created`**:
```json
{
  "id": "ee0e8400-e29b-41d4-a716-446655440050",
  "email": "manager@universitas.ac.id",
  "full_name": "Budi Santoso",
  "role": "admin_ojs",
  "must_change_password": true,
  "notif_email": true,
  "notif_telegram": false,
  "telegram_chat_id": null,
  "temp_password": "aB3xQr9mNkLp"
}
```

> **`temp_password`** ditampilkan **sekali saja** di response ini — backend tidak menyimpannya dalam bentuk plaintext (hanya bcrypt hash). Frontend **wajib** menampilkan nilai ini kepada `saas_admin` yang sedang login agar dapat diteruskan kepada pengguna baru. Pengguna baru wajib ganti password saat pertama kali login (`must_change_password: true`).

---

### `GET /api/v1/admin/users`

List semua user di platform.

**Response `200 OK`**:
```json
[
  {
    "id": "ee0e8400-e29b-41d4-a716-446655440050",
    "email": "manager@universitas.ac.id",
    "role": "admin_ojs",
    "is_active": true
  }
]
```

---

### `PATCH /api/v1/admin/users/{user_id}`

Update status atau role user. Semua field opsional.

**Request body**:
```json
{
  "is_active": false,
  "role": "viewer"
}
```

**Response `200 OK`**:
```json
{
  "id": "ee0e8400-e29b-41d4-a716-446655440050",
  "is_active": false,
  "role": "viewer"
}
```

**Errors**:
| Status | `detail` |
|---|---|
| 404 | `"User tidak ditemukan"` |

---

### `DELETE /api/v1/admin/users/{user_id}`

Hapus user permanen. **Response `204 No Content`**.

---

### `POST /api/v1/admin/tenants`

Buat tenant baru (organisasi/institusi baru di platform).

**Request body**:
```json
{
  "name": "Universitas Nusantara",
  "slug": "univ-nusantara"
}
```

**Response `201 Created`**:
```json
{
  "id": "dd0e8400-e29b-41d4-a716-446655440040",
  "name": "Universitas Nusantara",
  "slug": "univ-nusantara",
  "is_active": true
}
```

---

### `GET /api/v1/admin/tenants`

List semua tenant di platform.

**Response `200 OK`**:
```json
[
  {
    "id": "dd0e8400-e29b-41d4-a716-446655440040",
    "name": "Universitas Nusantara",
    "slug": "univ-nusantara",
    "is_active": true
  }
]
```

---

## 9. RBAC — Hak Akses per Role

| Fitur | `saas_admin` | `admin_ojs` | `viewer` |
|---|:---:|:---:|:---:|
| Dashboard stats | ✅ | ✅ | ✅ |
| List targets | ✅ | ✅ | ✅ |
| Tambah/hapus target | ✅ | ✅ | ❌ |
| Verifikasi target | ✅ | ✅ | ❌ |
| Plugin guide & API key | ✅ | ✅ | ❌ |
| Mulai scan | ✅ | ✅ | ❌ |
| Lihat findings | ✅ | ✅ | ✅ |
| Toggle false positive | ✅ | ✅ | ❌ |
| Download laporan | ✅ | ✅ | ✅ |
| Manajemen user (admin) | ✅ | ❌ | ❌ |
| Manajemen tenant (admin) | ✅ | ❌ | ❌ |
| Edit profil sendiri | ✅ | ✅ | ✅ |
| Ganti password sendiri | ✅ | ✅ | ✅ |

> Frontend harus menyembunyikan (atau menonaktifkan) tombol/menu yang tidak sesuai role user. Role tersedia dari `GET /api/v1/auth/me` field `role`.

---

## 10. TypeScript Types Lengkap

Salin ke `src/types/api.ts` di project Next.js:

```typescript
// --- Auth ---

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  must_change_password: boolean
}

export interface RefreshRequest {
  refresh_token: string
}

export interface LogoutRequest {
  refresh_token: string
}

export interface UserProfile {
  id: string
  email: string
  full_name: string
  role: UserRole
  must_change_password: boolean
  notif_email: boolean
  notif_telegram: boolean
  telegram_chat_id: string | null
}

export interface UpdateProfileRequest {
  full_name?: string
  notif_email?: boolean
  notif_telegram?: boolean
  telegram_chat_id?: string | null
}

export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}

export type UserRole = 'saas_admin' | 'admin_ojs' | 'viewer'

// --- Targets ---

export interface OJSTarget {
  id: string
  name: string
  url: string
  is_verified: boolean
  plugin_connected: boolean
  ojs_version: string | null
  created_at: string
}

export interface CreateTargetRequest {
  name: string
  url: string
}

export interface VerifyTargetResponse {
  verified: boolean
  method: 'file' | 'dns' | null
}

export interface PluginGuideResponse {
  target_id: string
  api_key: string
  endpoint: string
  instructions: string
}

export interface RegenerateKeyResponse {
  api_key: string
}

// --- Scans ---

export type ScanType = 'internal' | 'external' | 'full'
export type ScanStatus = 'queued' | 'running' | 'completed' | 'failed'
export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low'

export interface ScanProgress {
  stage: string
  current_step: number
  total_steps: number
}

export interface ScanJob {
  id: string
  target_id: string
  scan_type: ScanType
  status: ScanStatus
  overall_score: number | null
  risk_level: SeverityLevel | null
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  progress: ScanProgress | null
  created_at: string
}

export interface StartScanRequest {
  target_id: string
  scan_type: ScanType
}

export interface ScanFinding {
  id: string
  finding_type: string
  category: string
  title: string
  description: string
  affected_path: string
  evidence: string
  remediation: string
  severity: SeverityLevel
  cvss_score: number
  cve_id: string | null
  owasp_category: string | null
  is_false_positive: boolean
}

// --- Dashboard ---

export interface DashboardStats {
  targets: {
    total: number
  }
  scans: {
    last_30_days: number
    completed: number
    failed: number
  }
  security_posture: {
    average_score: number | null
  }
  findings_summary: {
    critical: number
    high: number
  }
}

// --- Reports ---

export interface Report {
  id: string
  job_id: string
  format: 'pdf' | 'json'
  file_size_bytes: number | null
  created_at: string
}

export interface ReportJsonResponse {
  job_id: string
  scan_type: ScanType
  status: ScanStatus
  overall_score: number | null
  risk_level: SeverityLevel | null
  findings: Array<{
    title: string
    severity: SeverityLevel
    cvss_score: number
    description: string
    remediation: string
  }>
}

// --- Admin ---

export interface AdminUserListItem {
  id: string
  email: string
  role: UserRole
  is_active: boolean
}

export interface CreateUserRequest {
  email: string
  full_name: string
  role: UserRole
  tenant_id?: string
}

/** temp_password hanya ada di response POST /admin/users — ditampilkan sekali lalu tidak bisa diambil lagi */
export interface CreateUserResponse extends UserProfile {
  temp_password: string
}

export interface UpdateUserRequest {
  is_active?: boolean
  role?: UserRole
}

export interface Tenant {
  id: string
  name: string
  slug: string
  is_active: boolean
}

export interface CreateTenantRequest {
  name: string
  slug: string
}

// --- Error ---

export interface ApiError {
  detail: string
}
```

---

## 11. Contoh HTTP Client Setup (Next.js)

### `src/lib/api-client.ts`

```typescript
import type { TokenResponse, ApiError } from '@/types/api'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://api-ojsdef.zentaza.online'

let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return false

  const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })

  if (!res.ok) {
    localStorage.removeItem('refresh_token')
    return false
  }

  const data: TokenResponse = await res.json()
  setAccessToken(data.access_token)
  localStorage.setItem('refresh_token', data.refresh_token)
  return true
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }

  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`
  }

  let res = await fetch(`${BASE_URL}${path}`, { ...options, headers })

  // Token expired — coba refresh sekali
  if (res.status === 401) {
    const refreshed = await refreshAccessToken()
    if (refreshed && accessToken) {
      headers['Authorization'] = `Bearer ${accessToken}`
      res = await fetch(`${BASE_URL}${path}`, { ...options, headers })
    }
  }

  if (res.status === 401 || res.status === 403) {
    if (typeof window !== 'undefined') {
      window.location.href = '/login'
    }
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const error: ApiError = await res.json().catch(() => ({ detail: 'Terjadi kesalahan' }))
    throw new Error(error.detail)
  }

  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}
```

### Contoh penggunaan

```typescript
import { apiFetch } from '@/lib/api-client'
import type { DashboardStats, ScanJob, OJSTarget } from '@/types/api'

// Ambil stats dashboard
const stats = await apiFetch<DashboardStats>('/api/v1/dashboard/stats')

// Mulai scan
const job = await apiFetch<ScanJob>('/api/v1/scans', {
  method: 'POST',
  body: JSON.stringify({ target_id: 'uuid-target', scan_type: 'full' }),
})

// Polling status scan (setiap 4 detik sampai selesai)
async function pollScanStatus(jobId: string): Promise<ScanJob> {
  const job = await apiFetch<ScanJob>(`/api/v1/scans/${jobId}`)
  if (job.status === 'running' || job.status === 'queued') {
    await new Promise(r => setTimeout(r, 4000))
    return pollScanStatus(jobId)
  }
  return job
}
```

---

## 12. Tabel Error Codes

| HTTP Status | Situasi | Tindakan Frontend |
|---|---|---|
| `400` | Validasi gagal, target belum diverifikasi | Tampilkan pesan dari field `detail` |
| `401` | Token expired atau tidak valid | Coba refresh token; jika gagal, redirect login |
| `403` | Role tidak cukup atau akun nonaktif | Tampilkan "Akses ditolak" |
| `404` | Resource tidak ditemukan | Tampilkan pesan kosong atau halaman 404 |
| `422` | Request body tidak sesuai schema | Cek tipe data yang dikirim |
| `500` | Internal server error | Tampilkan "Terjadi kesalahan server, coba lagi" |

---

## Catatan Tambahan

### Health check
```
GET /health
```
Response `200 OK`: `{"status": "ok"}` — tidak butuh autentikasi. Gunakan untuk ping saat app load.

### OpenAPI docs (development only)
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### Plugin callback — bukan untuk frontend
Endpoint `POST /plugin/v1/callback` digunakan oleh **plugin PHP di server OJS**, bukan frontend. Frontend tidak perlu memanggil endpoint ini.

### Versi API
Semua endpoint stabil berada di `/api/v1`. Tidak ada versioning lain saat ini.
