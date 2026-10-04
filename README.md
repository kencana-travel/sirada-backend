# Kencana Analytics — Backend

Backend untuk sistem analisis Big Data Kencana Travel: **Segmentasi Pasar**,
**Forecasting Demand**, dan **Analisis Performa Rute**. Dibangun mengacu pada
DFD Level 0/1, ERD, Class Diagram, dan Use Case Diagram yang sudah disusun
sebelumnya, serta menyesuaikan tampilan UI/UX (Login, Dashboard, Data Transaksi,
Segmentasi, Forecasting, Performa Rute) yang sudah dikirim.

## 1. Rancangan Arsitektur

```
Frontend (UI/UX yang sudah ada)
        |
        v  HTTP + JWT
+-------------------------+
|   FastAPI (app/main.py) |
|  - Router per modul     |
|  - Auth (JWT + role)    |
+-------------------------+
        |
        v
+-------------------------+        +----------------------+
|  Service Layer          | -----> | scikit-learn (KMeans) |
|  - segmentasi_service   |        | statsmodels (ARIMA)   |
|  - forecasting_service  |        |                      |
|  - performa_service     |        +----------------------+
+-------------------------+
        |
        v  SQLAlchemy ORM
+-------------------------+
|  Database (SQLite,      |
|  bisa ganti PostgreSQL) |
+-------------------------+
```

Stack: **FastAPI** (REST API) + **SQLAlchemy** (ORM) + **SQLite** (default,
tinggal ganti `DATABASE_URL` env var ke PostgreSQL untuk produksi tanpa ubah kode) +
**scikit-learn** (K-Means) + **statsmodels** (forecasting time-series).

## 2. Skema Database (sesuai ERD/Class Diagram)

`Cabang`, `Rute`, `Armada`, `Jadwal`, `Member`, `JenisPaket`, `Transaksi` (fact table),
`Pengguna` (akun login: Admin/Owner/KepalaOutlet).

## 3. Peta Endpoint ke Halaman UI

| Halaman UI | Endpoint |
|---|---|
| Login | `POST /api/auth/login` |
| Dashboard | `GET /api/dashboard/summary`, `/distribusi-member`, `/aktivitas-terkini` |
| Data Transaksi | `GET /api/transaksi` (filter+pagination), `POST /api/transaksi`, `GET /api/transaksi/export` |
| Segmentasi | `GET /api/segmentasi/ringkasan`, `GET /api/segmentasi/cluster` (RFM+K-Means) |
| Forecasting | `GET /api/forecasting/rute-tersedia`, `POST /api/forecasting/run` (ARIMA) |
| Performa Rute | `GET /api/performa-rute`, `GET /api/performa-rute/vip-vs-reguler` |

Dokumentasi interaktif lengkap (Swagger) otomatis tersedia di `/docs` setelah server jalan.

## 4. Algoritma yang Dipakai (sesuai kesepakatan sebelumnya)

- **Segmentasi Pasar**: RFM (Recency/Frequency/Monetary) dihitung per pelanggan,
  lalu di-cluster pakai **K-Means** (scikit-learn), diberi label Tier Platinum/Gold/Silver/Calon Member
  berdasarkan ranking nilai monetary tiap cluster.
- **Forecasting Demand**: **ARIMA(p, d, q)** (statsmodels) per rute. Nilai d ditentukan dari uji
  ADF (differencing maks. 2 kali), p dan q dipilih dari kandidat 0-2 dengan AIC terkecil.
  Akurasi dihitung lewat train/test split 14 hari terakhir (MAE, RMSE, MAPE).
- **Performa Rute**: agregasi statistik deskriptif (total trip, load factor, perbandingan VIP vs Reguler).

## 5. Role & Akses (sesuai Use Case Diagram)

- **Admin**: akses penuh — input data, jalankan segmentasi/forecasting, tambah transaksi.
- **Owner** & **KepalaOutlet**: hanya bisa melihat dashboard/laporan (read-only),
  tidak bisa tambah transaksi atau menjalankan model (dibatasi lewat `require_roles()`).

## 6. Cara Menjalankan

```bash
# 1. Install dependency
pip install -r requirements.txt

# 2. Load data transaksi ke database (pakai data sintetis yang sudah kita buat sebelumnya,
#    atau ganti dengan CSV data asli Kencana Travel dengan struktur kolom yang sama)
python -m app.load_data data/kencana_transaksi_gabungan.csv

# 3. Buat akun login default (admin/owner/kepala outlet)
python -m app.seed_users

# 4. Jalankan server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Buka `http://localhost:8000/docs` untuk mencoba semua endpoint langsung dari browser.

### Akun default (dari `seed_users.py`)
| Role | Email | Password |
|---|---|---|
| Admin | admin@kencanatravel.co.id | admin123 |
| Owner | owner@kencanatravel.co.id | owner123 |
| KepalaOutlet | kepala.solo@kencanatravel.co.id | kepala123 |

**PENTING**: ganti `JWT_SECRET` (env var) dan password default sebelum dipakai di lingkungan nyata.

## 7. Catatan & Keterbatasan (jujur, biar tidak salah paham)

1. **Nama pelanggan pada data sintetis dibuat acak per transaksi** (bukan ID pelanggan asli
   yang konsisten), karena data mentah dari Kencana tidak menyertakan data pribadi penumpang.
   Efeknya, hasil RFM per "pelanggan" pada dataset demo ini kurang representatif
   (satu nama bisa kebagian ribuan transaksi karena hanya ~190 kombinasi nama yang dipakai
   generator). **Begitu data transaksi asli Kencana (dengan ID pelanggan/nomor HP yang konsisten)
   tersedia, cukup ganti sumber data di `load_data.py` — seluruh logic RFM+K-Means tidak perlu diubah.**
2. **Endpoint `performa-rute` dan `segmentasi/cluster` memuat seluruh tabel transaksi ke pandas**
   di setiap request (~3-4 detik dengan 464rb baris di SQLite). Untuk produksi dengan data
   terus bertambah, sebaiknya ditambah caching (mis. hasil dihitung berkala lewat scheduled job,
   bukan real-time tiap request) atau pre-aggregation di level database.
3. **Harga tiket di endpoint tambah-transaksi masih hardcode** (Rp105.000) — idealnya diambil
   dari tabel tarif per rute+layanan; belum ada tabel tarif terpisah di skema ini.
4. Belum ada endpoint **generate PDF** untuk tombol "Export Laporan PDF" di UI — baru tersedia
   export CSV. Bisa ditambah pakai library seperti `reportlab`/`weasyprint` bila dibutuhkan.
5. Ini backend siap-jalan untuk skala development/demo. Untuk produksi: pindah ke PostgreSQL
   (tinggal ganti `DATABASE_URL`), pasang rate-limiting, dan audit ulang secret key JWT.

## Deploy ke Railway

1. Di project Railway: **New → Database → PostgreSQL**, lalu **New → GitHub Repo** (repo backend ini).
2. Tab **Variables** service backend:
   | Variabel | Nilai |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
   | `JWT_SECRET` | string acak panjang (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
   | `FRONTEND_URL` | `https://<frontend>.up.railway.app` (untuk link email & CORS) |
   | `RESEND_API_KEY` | API key Resend |
   | `MAIL_FROM` | `SIRADA Kencana <onboarding@resend.dev>` atau alamat di domain terverifikasi |
   | `ADMIN_EMAIL`, `ADMIN_PASSWORD` | akun Admin pertama (email asli, password ≥ 8 karakter) |
3. **Settings → Networking → Generate Domain**.

Konfigurasi build/start ada di `railway.json`. Saat start, `python -m app.bootstrap` menjalankan migrasi,
memuat `data/kencana_transaksi_gabungan.csv` bila database masih kosong (deploy pertama, ±2–5 menit),
dan membuat akun Admin pertama. Deploy berikutnya melewati langkah pemuatan data.
