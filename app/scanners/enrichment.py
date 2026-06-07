"""Data enrichment terpusat untuk semua finding type scanner.

Setiap entry memetakan finding_type ke daftar referensi standar (OWASP/CWE/
vendor) dan langkah perbaikan bernomor dalam Bahasa Indonesia. make_finding()
di scanners/models.py melakukan lookup otomatis ke dict ini — lihat Task 4.

Finding type yang butuh konten dinamis (mis. cve_ojs dengan {cve_id}) di-
override eksplisit oleh caller; lookup di sini hanya dipakai sebagai fallback
saat caller tidak memberikan references/remediation_steps secara eksplisit.
"""

ENRICHMENT_DATA: dict[str, dict[str, list[str]]] = {
    # ==================== INTERNAL FINDINGS ====================
    "debug_mode_active": {
        "remediation_steps": [
            "Buka file config.inc.php di direktori root instalasi OJS.",
            "Temukan section [debug] dan ubah semua flag menjadi Off: display_errors = Off, show_errors = Off, show_stacktrace = Off",
            "Simpan file config.inc.php.",
            "Reload web server: sudo systemctl reload nginx (atau apache2).",
            "Verifikasi: akses URL yang tidak valid di OJS dan pastikan tidak ada stack trace PHP yang tampil, hanya halaman error generik.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/209.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
            "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html",
        ],
    },
    "force_ssl_disabled": {
        "remediation_steps": [
            "Buka file config.inc.php di direktori root OJS.",
            "Cari baris force_ssl = Off di section [security] dan ubah menjadi force_ssl = On.",
            "Pastikan sertifikat SSL/TLS sudah terpasang dan valid di web server sebelum mengaktifkan force_ssl.",
            "Tambahkan redirect HTTP→HTTPS di konfigurasi Nginx: return 301 https://$host$request_uri;",
            "Reload web server: sudo systemctl reload nginx",
            "Verifikasi: akses http://<domain> dan pastikan otomatis redirect ke https://<domain>.",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/319.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "smtp_no_auth": {
        "remediation_steps": [
            "Buka file config.inc.php, temukan section [email].",
            "Set smtp_auth sesuai mekanisme autentikasi server SMTP (mis. smtp_auth = LOGIN atau PLAIN).",
            "Isi smtp_username dan smtp_password dengan kredensial akun SMTP yang valid.",
            "Pastikan koneksi SMTP menggunakan TLS: smtp_secure = tls atau ssl sesuai port (587/465).",
            "Kirim email uji dari OJS (mis. notifikasi pengguna baru) untuk memastikan autentikasi berhasil.",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/306.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
        ],
    },
    "db_password_empty": {
        "remediation_steps": [
            "Generate password database yang kuat (minimal 16 karakter campuran): openssl rand -base64 24",
            "Set password baru di PostgreSQL: ALTER USER ojsdef WITH PASSWORD '<password_baru>';",
            "Perbarui kredensial database di config.inc.php (parameter password di section [database]).",
            "Restart layanan agar konfigurasi baru terbaca: sudo systemctl restart php8.1-fpm nginx",
            "Hapus riwayat shell yang berisi password lama bila perlu: history -c",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/521.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
        ],
    },
    "api_key_too_short": {
        "remediation_steps": [
            "Generate API key baru dengan panjang minimal 32 karakter acak: openssl rand -hex 32",
            "Perbarui nilai API key di pengaturan plugin OJSDef pada panel admin OJS (Settings → Website → Plugins → OJSDef).",
            "Perbarui juga nilai yang sesuai di dashboard OJSDef agar pairing tetap valid.",
            "Simpan API key baru di tempat aman (password manager) — jangan commit ke version control.",
            "Lakukan rotasi API key secara berkala (mis. setiap 90 hari).",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/326.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html",
        ],
    },
    "multiple_superadmin": {
        "remediation_steps": [
            "Login ke OJS sebagai Site Administrator.",
            "Buka menu Administration → Site Management → Users.",
            "Filter pengguna dengan role 'Site Administrator'.",
            "Identifikasi akun Site Administrator yang tidak diperlukan.",
            "Klik nama pengguna → Edit → ubah role menjadi 'Journal Manager' untuk jurnal yang relevan, atau nonaktifkan akun.",
            "Pertahankan hanya 1 akun Site Administrator aktif sebagai prinsip least privilege.",
            "Dokumentasikan akun yang diubah untuk audit trail.",
        ],
        "references": [
            "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
            "https://cwe.mitre.org/data/definitions/269.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html",
            "https://docs.pkp.sfu.ca/admin-guide/en/users-and-roles",
        ],
    },
    "inactive_high_priv_account": {
        "remediation_steps": [
            "Login sebagai Site Administrator → Administration → Site Management → Users.",
            "Filter pengguna dengan role tinggi (Site Administrator/Journal Manager) dan urutkan berdasarkan tanggal login terakhir.",
            "Identifikasi akun yang tidak aktif lebih dari 90 hari.",
            "Nonaktifkan akun tersebut (Disable User) atau hapus jika sudah tidak relevan.",
            "Terapkan kebijakan review akses berkala (mis. setiap kuartal) untuk mencegah akumulasi akun idle.",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/613.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html",
        ],
    },
    "modified_core_file": {
        "remediation_steps": [
            "SEGERA: Aktifkan maintenance mode dan isolasi server dari traffic publik jika dicurigai kompromi aktif.",
            "Bandingkan file yang termodifikasi dengan checksum resmi versi OJS terpasang (lihat 'affected_path' pada temuan).",
            "Backup file termodifikasi untuk forensik: cp <file> <file>.suspect.bak",
            "Timpa file core dengan versi resmi dari arsip rilis OJS: https://github.com/pkp/ojs/releases",
            "Audit log akses web server untuk mengidentifikasi waktu dan sumber modifikasi.",
            "Reset semua kredensial admin dan API key setelah pembersihan selesai.",
            "Jalankan ulang scan integritas file untuk memastikan tidak ada file lain yang termodifikasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            "https://cwe.mitre.org/data/definitions/494.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
        ],
    },
    "modified_plugin_file": {
        "remediation_steps": [
            "Identifikasi plugin yang file-nya termodifikasi dari 'affected_path' pada temuan.",
            "Backup file untuk forensik, lalu timpa dengan versi resmi dari repository/marketplace plugin OJS.",
            "Jika plugin pihak ketiga, unduh ulang dari sumber terpercaya dan verifikasi checksum jika tersedia.",
            "Audit log akses untuk mengidentifikasi kapan dan bagaimana modifikasi terjadi.",
            "Pertimbangkan menonaktifkan plugin sementara jika tidak yakin dengan integritasnya.",
            "Jalankan ulang scan file integrity setelah pembersihan untuk konfirmasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            "https://cwe.mitre.org/data/definitions/494.html",
            "https://docs.pkp.sfu.ca/admin-guide/en/plugins",
        ],
    },
    "missing_core_file": {
        "remediation_steps": [
            "Identifikasi file core yang hilang dari 'affected_path' pada temuan.",
            "Bandingkan dengan struktur direktori resmi versi OJS yang sama dari https://github.com/pkp/ojs/releases",
            "Salin ulang file yang hilang dari arsip rilis resmi (jangan dari sumber tidak terpercaya).",
            "Periksa permission file setelah penyalinan: chown -R www-data:www-data <path> && chmod 644 <file>",
            "Jalankan ulang scan file integrity untuk memastikan struktur file sudah lengkap dan utuh.",
        ],
        "references": [
            "https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/",
            "https://cwe.mitre.org/data/definitions/494.html",
            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
        ],
    },
    "gambling_content": {
        "remediation_steps": [
            "SEGERA: Identifikasi lokasi konten berjudi dari 'affected_path' (artikel, halaman, atau metadata jurnal).",
            "Hapus konten berjudi dari database melalui panel admin OJS atau langsung via psql.",
            "Audit seluruh artikel dan halaman statis untuk konten serupa (cari kata kunci terkait judi/taruhan).",
            "Periksa log akses dan log perubahan konten untuk mengidentifikasi akun yang melakukan injeksi.",
            "Reset password seluruh akun dengan hak edit konten (Editor, Section Editor, Journal Manager).",
            "Audit plugin pihak ketiga yang memungkinkan injeksi konten (rich text editor, file upload).",
            "Jalankan ulang scan content injection setelah pembersihan untuk konfirmasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/74.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html",
        ],
    },
    "eval_base64_injection": {
        "remediation_steps": [
            "SEGERA: Pertimbangkan mengisolasi server dari internet jika memungkinkan saat proses pembersihan.",
            "Identifikasi lokasi persis konten berbahaya dari field 'affected_path' di temuan ini.",
            "Hapus konten yang mengandung eval(base64_decode(...)) dari database OJS menggunakan phpMyAdmin atau psql.",
            "Audit seluruh file PHP di server: find /path/to/ojs -name \"*.php\" | xargs grep -l \"eval(base64\"",
            "Periksa log akses web server (access.log) untuk mengidentifikasi kapan dan bagaimana injeksi terjadi.",
            "Reset password semua akun admin OJS dan pastikan MFA aktif jika tersedia.",
            "Update OJS ke versi terbaru dan semua plugin ke versi terbaru.",
            "Jalankan full scan ulang setelah pembersihan untuk konfirmasi tidak ada sisa injeksi.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/94.html",
            "https://cwe.mitre.org/data/definitions/506.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html",
        ],
    },
    "hidden_iframe_injection": {
        "remediation_steps": [
            "Identifikasi lokasi iframe tersembunyi dari 'affected_path' dan 'evidence' pada temuan.",
            "Hapus tag <iframe> mencurigakan dari konten artikel/halaman melalui database atau panel admin.",
            "Audit seluruh konten yang dapat diedit pengguna untuk pola iframe serupa (display:none, width=0, height=0).",
            "Terapkan sanitasi HTML pada input konten menggunakan library seperti HTML Purifier.",
            "Tambahkan Content-Security-Policy dengan directive frame-src yang ketat untuk mencegah injeksi iframe eksternal.",
            "Jalankan ulang scan content injection untuk konfirmasi pembersihan.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/79.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
        ],
    },
    "phishing_tld_link": {
        "remediation_steps": [
            "Identifikasi tautan mencurigakan dari 'affected_path' dan 'evidence' pada temuan (domain dengan TLD tidak lazim).",
            "Hapus atau ganti tautan tersebut dari konten artikel/halaman jurnal.",
            "Audit seluruh konten yang mengandung tautan eksternal untuk pola serupa.",
            "Periksa akun yang menambahkan tautan tersebut dan reset kredensialnya jika dicurigai disusupi.",
            "Edukasi editor/penulis untuk selalu memverifikasi tautan eksternal sebelum dipublikasikan.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/601.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html",
        ],
    },
    "js_redirect_injection": {
        "remediation_steps": [
            "Identifikasi lokasi script redirect dari 'affected_path' dan 'evidence' pada temuan.",
            "Hapus kode JavaScript injeksi (window.location, document.location, meta refresh mencurigakan) dari konten/template.",
            "Audit template tema dan plugin pihak ketiga untuk kode serupa yang disisipkan.",
            "Terapkan Content-Security-Policy dengan directive script-src yang membatasi sumber script.",
            "Reset kredensial akun yang memiliki akses edit template/tema.",
            "Jalankan ulang scan content injection untuk konfirmasi pembersihan.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/601.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
        ],
    },
    "disabled_plugins_installed": {
        "remediation_steps": [
            "Login sebagai Site/Journal Administrator → Settings → Website → Plugins.",
            "Tinjau daftar plugin yang terpasang namun nonaktif dari 'affected_path' pada temuan.",
            "Untuk plugin yang tidak akan dipakai: uninstall sepenuhnya untuk mengurangi attack surface (Plugin Gallery → Uninstall).",
            "Untuk plugin yang mungkin dipakai kembali: pastikan tetap diperbarui ke versi terbaru meski nonaktif.",
            "Dokumentasikan keputusan (uninstall/keep) untuk audit trail konfigurasi jurnal.",
        ],
        "references": [
            "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            "https://cwe.mitre.org/data/definitions/1104.html",
            "https://docs.pkp.sfu.ca/admin-guide/en/plugins",
        ],
    },
    "excessive_active_plugins": {
        "remediation_steps": [
            "Login sebagai Site/Journal Administrator → Settings → Website → Plugins.",
            "Tinjau daftar plugin aktif dan identifikasi mana yang benar-benar digunakan oleh jurnal.",
            "Nonaktifkan plugin yang tidak esensial untuk mengurangi permukaan serangan dan beban server.",
            "Pastikan seluruh plugin yang tetap aktif diperbarui ke versi terbaru secara berkala.",
            "Lakukan review plugin aktif setiap kali ada upgrade major OJS.",
        ],
        "references": [
            "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            "https://docs.pkp.sfu.ca/admin-guide/en/plugins",
        ],
    },
