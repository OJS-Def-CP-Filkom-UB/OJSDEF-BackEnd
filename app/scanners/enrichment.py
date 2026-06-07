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
    # ==================== EXTERNAL FINDINGS ====================
    "ojs_version_exposed": {
        "remediation_steps": [
            "Buka file templates/frontend/components/header.tpl atau lib/pkp/templates/common/footer.tpl dan hapus tag generator/meta yang menampilkan versi OJS.",
            "Periksa juga file README, CHANGELOG, dan dokumen publik lain di webroot yang mungkin mengekspos versi.",
            "Tambahkan aturan Nginx untuk memblokir akses dokumen tersebut: location ~* (README|CHANGELOG)\\.(md|txt)$ { deny all; }",
            "Verifikasi dengan curl https://<domain> | grep -i \"ojs\" untuk memastikan versi tidak lagi terekspos di HTML.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/200.html",
            "https://docs.pkp.sfu.ca/dev/documentation/en/getting-started",
        ],
    },
    "outdated_ojs_version": {
        "remediation_steps": [
            "Cek versi OJS terbaru yang stabil di https://pkp.sfu.ca/ojs/ojs_download/",
            "Backup database dan seluruh file OJS sebelum upgrade: pg_dump ojsdb > backup.sql && tar -czf ojs-backup.tar.gz /path/to/ojs",
            "Baca catatan rilis (release notes) untuk perubahan breaking dan langkah migrasi khusus.",
            "Ikuti panduan upgrade resmi: https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            "Jalankan php tools/upgrade.php upgrade setelah file baru di-deploy.",
            "Verifikasi fungsionalitas jurnal pasca-upgrade dan jalankan ulang scan untuk konfirmasi versi sudah terbaru.",
        ],
        "references": [
            "https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/",
            "https://cwe.mitre.org/data/definitions/1104.html",
            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            "https://pkp.sfu.ca/category/news/announcements/releases/",
        ],
    },
    "ssl_expired": {
        "remediation_steps": [
            "Perbarui sertifikat SSL segera — sertifikat kedaluwarsa menyebabkan semua pengunjung melihat peringatan keamanan.",
            "Jika menggunakan Let's Encrypt: jalankan sudo certbot renew --force-renewal",
            "Jika menggunakan CA komersial: beli/renew sertifikat baru dari penyedia CA, lalu install di web server.",
            "Setelah install sertifikat baru, reload Nginx: sudo systemctl reload nginx",
            "Aktifkan auto-renewal untuk mencegah kedaluwarsa di masa depan: sudo systemctl enable certbot.timer",
            "Verifikasi sertifikat baru: openssl s_client -connect <domain>:443 | grep \"notAfter\"",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/298.html",
            "https://letsencrypt.org/docs/certificate-compatibility/",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "ssl_expiring_soon": {
        "remediation_steps": [
            "Cek tanggal kedaluwarsa pasti: openssl s_client -connect <domain>:443 | grep \"notAfter\"",
            "Jika menggunakan Let's Encrypt: pastikan certbot.timer aktif untuk auto-renewal: sudo systemctl status certbot.timer",
            "Jika auto-renewal tidak aktif, jalankan manual: sudo certbot renew",
            "Jika menggunakan CA komersial: ajukan renewal sebelum tanggal kedaluwarsa ke penyedia CA.",
            "Setelah sertifikat baru terpasang, reload web server: sudo systemctl reload nginx",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/298.html",
            "https://letsencrypt.org/docs/certificate-compatibility/",
        ],
    },
    "weak_tls": {
        "remediation_steps": [
            "Buka konfigurasi Nginx (biasanya /etc/nginx/sites-available/<site>) dan temukan directive ssl_protocols.",
            "Nonaktifkan protokol lama: ssl_protocols TLSv1.2 TLSv1.3; (hapus SSLv3, TLSv1.0, TLSv1.1)",
            "Perbarui daftar cipher suite ke preset modern dari https://ssl-config.mozilla.org/ (pilih profil 'Intermediate').",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi konfigurasi dengan https://www.ssllabs.com/ssltest/ atau testssl.sh — targetkan grade A.",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/327.html",
            "https://ssl-config.mozilla.org/",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "http_no_https_redirect": {
        "remediation_steps": [
            "Buka konfigurasi server block Nginx untuk port 80 (HTTP).",
            "Tambahkan redirect permanen ke HTTPS: server { listen 80; server_name <domain>; return 301 https://$host$request_uri; }",
            "Pastikan tidak ada konten yang disajikan langsung melalui blok HTTP tersebut.",
            "Reload konfigurasi: sudo systemctl reload nginx",
            "Verifikasi: curl -I http://<domain> — harus mengembalikan status 301 dengan header Location: https://...",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/319.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html",
        ],
    },
    "missing_csp": {
        "remediation_steps": [
            "Tambahkan header Content-Security-Policy di blok server Nginx.",
            "Mulai dengan kebijakan moderat: add_header Content-Security-Policy \"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;\" always;",
            "Uji halaman jurnal dalam mode Report-Only (Content-Security-Policy-Report-Only) untuk mendeteksi resource yang terblokir.",
            "Sesuaikan whitelist sumber berdasarkan resource yang dibutuhkan tema/plugin OJS yang dipakai.",
            "Setelah stabil, terapkan sebagai kebijakan enforced (bukan report-only) dan reload Nginx.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/693.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html",
            "https://owasp.org/www-project-secure-headers/",
        ],
    },
    "missing_hsts": {
        "remediation_steps": [
            "Pastikan situs sudah sepenuhnya berjalan di HTTPS sebelum mengaktifkan HSTS.",
            "Tambahkan header di blok server HTTPS Nginx: add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;",
            "Mulai dengan max-age kecil (mis. 300 detik) untuk pengujian, lalu naikkan ke 31536000 (1 tahun) setelah yakin tidak ada masalah.",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header Strict-Transport-Security muncul.",
        ],
        "references": [
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
            "https://cwe.mitre.org/data/definitions/319.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html",
        ],
    },
    "missing_x_frame": {
        "remediation_steps": [
            "Tambahkan header di blok server Nginx: add_header X-Frame-Options \"SAMEORIGIN\" always;",
            "Atau gunakan directive frame-ancestors di Content-Security-Policy sebagai pengganti modern: frame-ancestors 'self';",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header X-Frame-Options atau frame-ancestors muncul.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/1021.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html",
        ],
    },
    "missing_referrer_policy": {
        "remediation_steps": [
            "Tambahkan header Referrer-Policy di konfigurasi Nginx server block.",
            "Gunakan nilai: add_header Referrer-Policy \"strict-origin-when-cross-origin\" always;",
            "Nilai strict-origin-when-cross-origin aman untuk mayoritas jurnal — hanya kirim origin (bukan full URL) saat cross-origin, dan tidak kirim apapun saat downgrade HTTPS→HTTP.",
            "Reload konfigurasi Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header Referrer-Policy muncul di respons.",
        ],
        "references": [
            "https://owasp.org/www-project-secure-headers/",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy",
            "https://cwe.mitre.org/data/definitions/200.html",
        ],
    },
    "missing_permissions_policy": {
        "remediation_steps": [
            "Tambahkan header Permissions-Policy di blok server {} konfigurasi Nginx.",
            "Contoh minimal untuk OJS: add_header Permissions-Policy \"geolocation=(), microphone=(), camera=(), payment=()\" always;",
            "Sesuaikan daftar fitur dengan kebutuhan jurnal (hapus fitur yang memang tidak dipakai).",
            "Reload konfigurasi Nginx: sudo systemctl reload nginx",
            "Verifikasi dengan curl -I https://<domain> dan cek header Permissions-Policy muncul.",
        ],
        "references": [
            "https://owasp.org/www-project-secure-headers/",
            "https://www.w3.org/TR/permissions-policy-1/",
        ],
    },
    "missing_x_content_type_options": {
        "remediation_steps": [
            "Tambahkan header di konfigurasi Nginx: add_header X-Content-Type-Options \"nosniff\" always;",
            "Kata kunci 'always' penting agar header muncul juga di halaman error (bukan hanya respons 200).",
            "Reload konfigurasi Nginx: sudo systemctl reload nginx",
            "Verifikasi di browser DevTools → Network tab → pilih request → Response Headers, cek X-Content-Type-Options: nosniff.",
        ],
        "references": [
            "https://owasp.org/www-project-secure-headers/",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options",
            "https://cwe.mitre.org/data/definitions/693.html",
        ],
    },
    "reflected_xss": {
        "remediation_steps": [
            "Identifikasi semua parameter input yang direfleksikan ke halaman tanpa encoding (prioritaskan parameter search/query).",
            "Terapkan output encoding pada setiap nilai yang dirender ke HTML — gunakan htmlspecialchars() dengan ENT_QUOTES di PHP.",
            "Implementasikan Content-Security-Policy (CSP) yang ketat untuk membatasi sumber script yang diizinkan.",
            "Validasi dan whitelist input di sisi server — tolak atau encode karakter '<', '>', '\"', \"'\", '/'.",
            "Pertimbangkan menggunakan library sanitasi seperti HTML Purifier untuk konten yang memang boleh mengandung HTML.",
            "Jalankan ulang scan setelah perbaikan untuk konfirmasi XSS sudah tidak terdeteksi.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/79.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
            "https://portswigger.net/web-security/cross-site-scripting/reflected",
        ],
    },
    "sql_error_exposed": {
        "remediation_steps": [
            "Nonaktifkan display_errors di PHP production: edit php.ini, set display_errors = Off, log_errors = On.",
            "Di config.inc.php OJS, pastikan show_errors = Off dan show_stacktrace = Off.",
            "Konfigurasi halaman error generik di Nginx agar tidak menampilkan detail backend: error_page 500 502 503 504 /50x.html;",
            "Audit query yang menghasilkan error tersebut dan pastikan menggunakan parameterized query/prepared statement.",
            "Reload PHP-FPM dan Nginx: sudo systemctl restart php8.1-fpm nginx",
            "Jalankan ulang scan untuk memastikan pesan error SQL tidak lagi terekspos ke pengguna.",
        ],
        "references": [
            "https://owasp.org/Top10/A03_2021-Injection/",
            "https://cwe.mitre.org/data/definitions/209.html",
            "https://cwe.mitre.org/data/definitions/89.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html",
        ],
    },
    "path_traversal": {
        "remediation_steps": [
            "Identifikasi endpoint yang rentan dari 'affected_path' pada temuan.",
            "Pastikan OJS dan seluruh plugin/dependency dalam keadaan versi terbaru — kerentanan path traversal sering sudah dipatch di rilis terbaru.",
            "Tambahkan aturan Nginx untuk memblokir pola traversal pada URL: location ~ \\.\\./ { deny all; }",
            "Validasi dan normalisasi seluruh input path di sisi aplikasi — tolak karakter '../' dan path absolut.",
            "Batasi permission filesystem agar proses web server tidak dapat membaca file di luar webroot (open_basedir di php.ini).",
            "Jalankan ulang scan vulnerability prober setelah perbaikan untuk konfirmasi.",
        ],
        "references": [
            "https://owasp.org/Top10/A01_2021-Broken_Access_Control/",
            "https://cwe.mitre.org/data/definitions/22.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html",
        ],
    },
    "exposed_git": {
        "remediation_steps": [
            "SEGERA: Asumsikan seluruh riwayat kode dan kemungkinan kredensial di repository sudah bocor.",
            "Hapus direktori .git dari direktori produksi: rm -rf /path/to/ojs/.git (deploy tanpa menyertakan .git ke webroot).",
            "Blokir akses di Nginx sebagai mitigasi cepat: location ~ /\\.git { deny all; return 404; }",
            "Audit riwayat commit untuk kredensial/secret yang mungkin pernah ter-commit, dan rotasi semua yang ditemukan.",
            "Terapkan proses deployment yang memisahkan source control dari direktori webroot (CI/CD yang hanya menyalin artefak build).",
            "Verifikasi: akses https://<domain>/.git/config — harus mendapat HTTP 403 atau 404.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/538.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html",
        ],
    },
    "exposed_env_file": {
        "remediation_steps": [
            "SEGERA: Asumsikan semua kredensial di .env sudah bocor — mulai rotasi semua password dan API key yang tersimpan di file tersebut.",
            "Periksa log akses web server (access.log) untuk mengetahui apakah .env sudah pernah diunduh oleh pihak lain.",
            "Pindahkan file .env ke direktori di luar webroot (satu level di atas direktori public/webroot OJS).",
            "Jika tidak bisa dipindahkan, blokir akses di Nginx: location ~ /\\.env { deny all; return 404; }",
            "Untuk Apache: tambahkan di .htaccess: <Files \".env\"> Order allow,deny Deny from all </Files>",
            "Update semua service yang menggunakan kredensial yang berpotensi terekspos (database, SMTP, API key pihak ketiga).",
            "Verifikasi perbaikan: akses https://<domain>/.env — harus mendapat HTTP 403 atau 404.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/538.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html",
            "https://www.acunetix.com/vulnerabilities/web/env-file-publicly-accessible/",
        ],
    },
    "phpinfo_exposed": {
        "remediation_steps": [
            "Identifikasi lokasi file phpinfo() dari 'affected_path' pada temuan (mis. info.php, test.php, phpinfo.php).",
            "Hapus file tersebut dari server: rm /path/to/ojs/<file>.php",
            "Audit direktori webroot untuk file uji/debug serupa yang mungkin tertinggal dari proses development.",
            "Tambahkan aturan deployment yang mencegah file uji ikut ter-deploy ke production (.gitignore, build exclude list).",
            "Verifikasi: akses https://<domain>/<file>.php — harus mendapat HTTP 404.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/200.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html",
        ],
    },
    "open_directory": {
        "remediation_steps": [
            "Identifikasi direktori yang directory listing-nya aktif dari 'affected_path' pada temuan.",
            "Nonaktifkan directory listing di Nginx: pastikan tidak ada directive autoindex on; pada blok location terkait.",
            "Tambahkan index.html/index.php kosong di direktori yang tidak boleh menampilkan listing sebagai lapisan pertahanan tambahan.",
            "Batasi akses langsung ke direktori upload/cache: location /files/ { internal; } atau gunakan signed URL.",
            "Reload Nginx: sudo systemctl reload nginx",
            "Verifikasi: akses https://<domain>/<direktori>/ — harus mendapat HTTP 403 atau 404, bukan daftar file.",
        ],
        "references": [
            "https://owasp.org/Top10/A05_2021-Security_Misconfiguration/",
            "https://cwe.mitre.org/data/definitions/548.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Securing_Cardholder_Data_Cheat_Sheet.html",
        ],
    },
    "ojs_admin_endpoint_exposed": {
        "remediation_steps": [
            "Pastikan halaman login admin (mis. /index.php/index/login) menggunakan HTTPS dan dilindungi rate limiting.",
            "Tambahkan rate limiting di Nginx: limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m; lalu terapkan di location terkait.",
            "Aktifkan CAPTCHA pada form login jika tersedia (plugin reCAPTCHA OJS).",
            "Pertimbangkan membatasi akses endpoint admin hanya dari IP tertentu (VPN/whitelist) menggunakan allow/deny di Nginx.",
            "Pastikan seluruh akun admin menggunakan password kuat dan, jika tersedia, aktifkan two-factor authentication.",
        ],
        "references": [
            "https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/",
            "https://cwe.mitre.org/data/definitions/307.html",
            "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
        ],
    },
    "ojs_oai_accessible": {
        "remediation_steps": [
            "Endpoint OAI-PMH (/oai) bersifat publik by design untuk interoperabilitas metadata jurnal — temuan ini bersifat informatif, bukan kerentanan kritis.",
            "Tinjau apakah eksposur metadata via OAI-PMH sesuai kebijakan jurnal (beberapa jurnal sengaja mengaktifkan untuk indexing Google Scholar/DOAJ).",
            "Jika ingin membatasi, konfigurasi akses OAI di Settings → Distribution → Indexing pada panel admin OJS.",
            "Jika perlu dibatasi di level jaringan, tambahkan whitelist IP untuk harvester tepercaya di Nginx.",
        ],
        "references": [
            "https://docs.pkp.sfu.ca/admin-guide/en/distribution",
            "https://www.openarchives.org/pmh/",
        ],
    },
    "cookie_missing_secure_flag": {
        "remediation_steps": [
            "Set session.cookie_secure = 1 di konfigurasi PHP (php.ini atau .htaccess), agar cookie hanya dikirim melalui HTTPS.",
            "Untuk Apache .htaccess: php_value session.cookie_secure 1",
            "Untuk Nginx dengan PHP-FPM: fastcgi_param PHP_VALUE \"session.cookie_secure=1\"; di blok location ~ \\.php$",
            "Pastikan situs sepenuhnya berjalan di HTTPS sebelum mengaktifkan flag ini agar sesi tidak rusak.",
            "Verifikasi di browser DevTools → Application → Cookies → kolom Secure harus tercentang.",
        ],
        "references": [
            "https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html",
            "https://cwe.mitre.org/data/definitions/614.html",
            "https://owasp.org/Top10/A02_2021-Cryptographic_Failures/",
        ],
    },
    "cookie_missing_httponly_flag": {
        "remediation_steps": [
            "Set session.cookie_httponly = 1 di konfigurasi PHP (php.ini atau per-directory .htaccess).",
            "Untuk Apache .htaccess: tambahkan php_value session.cookie_httponly 1",
            "Untuk Nginx dengan PHP-FPM: tambahkan fastcgi_param PHP_VALUE \"session.cookie_httponly=1\"; di blok location ~ \\.php$",
            "Verifikasi di browser DevTools → Application → Cookies → pastikan kolom HttpOnly tercentang untuk cookie OJS.",
        ],
        "references": [
            "https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html",
            "https://cwe.mitre.org/data/definitions/1004.html",
            "https://datatracker.ietf.org/doc/html/rfc6265#section-5.2.6",
        ],
    },
    "cookie_missing_samesite": {
        "remediation_steps": [
            "Set session.cookie_samesite = Strict di konfigurasi PHP jika jurnal tidak memerlukan cross-site navigation.",
            "Atau gunakan Lax jika jurnal menggunakan fitur deep-link dari situs eksternal (lebih umum dan aman untuk sebagian besar OJS).",
            "Untuk Apache .htaccess: php_value session.cookie_samesite \"Lax\"",
            "Untuk PHP 7.3+: dapat juga diset via ini_set('session.cookie_samesite', 'Lax'); di awal sesi.",
            "Verifikasi di DevTools → Application → Cookies → kolom SameSite harus menampilkan 'Strict' atau 'Lax'.",
        ],
        "references": [
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite",
            "https://cwe.mitre.org/data/definitions/352.html",
        ],
    },
    "cve_ojs": {
        "remediation_steps": [
            "Baca advisory keamanan resmi untuk CVE terkait di https://nvd.nist.gov/vuln/detail/ (lihat field cve_id pada temuan).",
            "Identifikasi versi OJS yang sudah memperbaiki kerentanan ini dari advisory PKP.",
            "Backup database dan semua file OJS sebelum upgrade: pg_dump ojsdb > backup.sql && tar -czf ojs-backup.tar.gz /path/to/ojs",
            "Download versi OJS terbaru dari https://pkp.sfu.ca/ojs/ojs_download/",
            "Ikuti panduan upgrade resmi PKP: https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            "Setelah upgrade, jalankan php tools/upgrade.php upgrade dari direktori OJS.",
            "Verifikasi fungsionalitas jurnal setelah upgrade, lalu jalankan ulang scan untuk konfirmasi CVE sudah resolved.",
        ],
        "references": [
            "https://nvd.nist.gov/vuln/detail/",
            "https://pkp.sfu.ca/category/news/announcements/releases/",
            "https://forum.pkp.sfu.ca/c/questions-and-answers/security/",
            "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
        ],
    },
}
