"""
Generator data transaksi sintetis SIRADA Kencana yang DIKALIBRASI dari laporan bulanan outlet
Kencana Travel (Januari-Agustus 2026, outlet Solo, Semarang, Tayu).

Angka acuan dari laporan asli:
- Penumpang per bulan (rata-rata Jul-Agu 2026): Solo ~4.240, Tayu ~1.520.
- Trip per bulan (rata-rata Jan-Jun 2026): Solo ~845, Tayu ~490; kursi per trip 9-11.
- Pendapatan per penumpang: Solo Rp76-97 rb, Semarang Rp93-94 rb, Tayu Rp113 rb.
  (Tarif per koridor dipilih agar rata-rata per outlet asal mendekati angka ini.)
- Diskon terhadap pendapatan: Semarang 6-11%, Solo 3-4%, Tayu ~2%. Tidak ada transaksi paket.
- Pola bulanan (trip Jan-Jun): Januari paling sepi, Mei paling ramai.

Volume rute diturunkan dari outlet Solo dan Tayu (arah balik dibuat seimbang). Outlet Semarang
tidak dipakai utuh karena juga melayani tujuan lain di luar ketiga cabang ini. Koridor utama
adalah Solo <-> Semarang.

Hasil: data/kencana_transaksi_gabungan.csv (format sama dengan template import + kolom
"Nama Pelanggan"). Periode 1 September 2023 - 31 Agustus 2026.

Jalankan: python scripts/buat_data_sintetis.py
"""
from __future__ import annotations

import string
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.services.referensi_service import LIBUR_NASIONAL, LIBUR_SEKOLAH  # noqa: E402

SEED = 20261004
rng = np.random.default_rng(SEED)

MULAI, SELESAI = date(2023, 9, 1), date(2026, 8, 31)
NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
KAPASITAS = {"Reguler": 12, "VIP": 8}

# ---------------------------------------------------------------------------- rute & jadwal
# Penumpang per hari pada level Jul-Agu 2026 (hasil kalibrasi dari laporan Kencana).
RUTE = {
    "Solo->Semarang": {"pax": 111, "kode": "SLO", "koridor": "Solo-Semarang"},
    "Semarang->Solo": {"pax": 111, "kode": "SMG", "koridor": "Solo-Semarang"},
    "Semarang->Tayu": {"pax": 35, "kode": "SMG", "koridor": "Semarang-Tayu"},
    "Tayu->Semarang": {"pax": 35, "kode": "TYU", "koridor": "Semarang-Tayu"},
    "Solo->Tayu": {"pax": 28, "kode": "SLO", "koridor": "Solo-Tayu"},
    "Tayu->Solo": {"pax": 15, "kode": "TYU", "koridor": "Solo-Tayu"},
}
JADWAL = {  # jam keberangkatan per layanan
    "Solo->Semarang": {"Reguler": [5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19],
                       "VIP": [6, 8, 10, 13, 15, 17, 19]},
    "Semarang->Solo": {"Reguler": [5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19],
                       "VIP": [6, 8, 10, 13, 15, 17, 19]},
    "Semarang->Tayu": {"Reguler": [5, 7, 9, 11, 13, 15, 17, 19], "VIP": [6, 12, 16]},
    "Tayu->Semarang": {"Reguler": [5, 6, 7, 9, 11, 13, 15, 17], "VIP": [6, 10, 14]},
    "Solo->Tayu": {"Reguler": [6, 9, 13, 16], "VIP": [7, 14]},
    "Tayu->Solo": {"Reguler": [6, 10, 14], "VIP": [8, 15]},
}
PORSI_VIP = {"Solo-Semarang": 0.30, "Semarang-Tayu": 0.22, "Solo-Tayu": 0.28}
# Bobot pilihan jam: pagi & sore lebih ramai.
BOBOT_JAM = {5: 0.8, 6: 1.3, 7: 1.4, 8: 1.2, 9: 1.0, 10: 0.9, 11: 0.8, 12: 0.8, 13: 0.9,
             14: 0.9, 15: 1.0, 16: 1.2, 17: 1.3, 18: 1.1, 19: 0.8}

# Tarif 2026 (Rp), per koridor & layanan. Tahun sebelumnya lebih rendah (lihat tarif()).
TARIF_2026 = {"Solo-Semarang": {"Reguler": 75_000, "VIP": 95_000},
              "Semarang-Tayu": {"Reguler": 100_000, "VIP": 125_000},
              "Solo-Tayu": {"Reguler": 120_000, "VIP": 145_000}}
DISKON = {"Non-Member": 0, "Member Umum": 10_000, "Member Mahasiswa": 15_000}

# Armada per cabang basis (kode, layanan).
ARMADA = {"Semarang": {"Reguler": 9, "VIP": 5}, "Solo": {"Reguler": 8, "VIP": 4},
          "Tayu": {"Reguler": 4, "VIP": 2}}
KODE_CABANG = {"Semarang": "SMG", "Solo": "SOLO", "Tayu": "TAYU"}

# ---------------------------------------------------------------------------- pola waktu
FAKTOR_BULAN = {1: 0.84, 2: 0.95, 3: 1.00, 4: 0.99, 5: 1.10, 6: 1.04, 7: 1.04, 8: 1.00,
                9: 0.95, 10: 0.97, 11: 0.95, 12: 1.06}
FAKTOR_HARI = [1.05, 0.85, 0.85, 0.95, 1.25, 1.05, 1.25]  # Senin..Minggu
LEBARAN = [date(2024, 4, 10), date(2025, 3, 31), date(2026, 3, 20)]


def faktor_tren(d: date) -> float:
    """Pertumbuhan ~8%/tahun; level 1,0 pada pertengahan 2026."""
    tahun = (d - date(2026, 7, 15)).days / 365.25
    return 1.08 ** tahun


def libur_sekolah_set() -> set[date]:
    hasil = set()
    for a, b in LIBUR_SEKOLAH:
        d, akhir = date.fromisoformat(a), date.fromisoformat(b)
        while d <= akhir:
            hasil.add(d)
            d += timedelta(days=1)
    return hasil


def faktor_kalender(d: date, sekolah: set[date]) -> float:
    f = 1.0
    if d.isoformat() in LIBUR_NASIONAL:
        f *= 1.45
    elif (d + timedelta(days=1)).isoformat() in LIBUR_NASIONAL:
        f *= 1.40  # H-1 libur: arus berangkat
    elif (d - timedelta(days=1)).isoformat() in LIBUR_NASIONAL:
        f *= 1.25  # H+1 libur: arus balik
    if d in sekolah:
        f *= 1.20
    for leb in LEBARAN:  # arus mudik & balik Lebaran
        k = (d - leb).days
        if -7 <= k <= -2:
            f *= 1.35 + 0.08 * (k + 7)
        elif k in (0, 1):
            f *= 0.75
        elif 2 <= k <= 7:
            f *= 1.75 - 0.08 * (k - 2)
    if (d.month == 12 and d.day >= 22) or (d.month == 1 and d.day <= 2):
        f *= 1.15  # Natal & tahun baru
    return f


def tarif(koridor: str, layanan: str, d: date) -> int:
    dasar = TARIF_2026[koridor][layanan]
    faktor = 1.0 if d.year >= 2026 else (0.95 if d.year == 2025 else 0.90)
    return int(round(dasar * faktor / 5000) * 5000)


# ---------------------------------------------------------------------------- pelanggan
DEPAN = ["Ahmad", "Budi", "Citra", "Dewi", "Eko", "Fajar", "Gita", "Hendra", "Indah", "Joko",
         "Kartika", "Lestari", "Maya", "Nanda", "Oki", "Putri", "Rizky", "Sari", "Tono", "Umi",
         "Vina", "Wahyu", "Yudi", "Zahra", "Agus", "Bayu", "Dimas", "Eka", "Fitri", "Galih",
         "Hana", "Ilham", "Kurnia", "Lukman", "Mega", "Nur", "Rina", "Sigit", "Tri", "Wulan",
         "Arif", "Bambang", "Desi", "Endah", "Feri", "Heru", "Iwan", "Laras", "Mira", "Novi",
         "Puji", "Rahmat", "Sri", "Teguh", "Yuni", "Anisa", "Bagus", "Dian", "Erna", "Yoga"]
TENGAH = ["", "Adi", "Ayu", "Dwi", "Eka", "Nur", "Putra", "Putri", "Rahma", "Sari", "Tri",
          "Wahyu", "Indra", "Kusuma", "Maulana", "Dewi", "Prasetya", "Ratna", "Setya", "Wijaya"]
BELAKANG = ["Santoso", "Wijaya", "Saputra", "Lestari", "Pratama", "Hidayat", "Kurniawan",
            "Nugroho", "Setiawan", "Susanti", "Rahayu", "Purnomo", "Hartono", "Wibowo",
            "Handayani", "Prasetyo", "Utomo", "Wulandari", "Kusuma", "Firmansyah", "Maharani",
            "Permana", "Ramadhan", "Safitri", "Suryadi", "Gunawan", "Yulianti", "Anggraini",
            "Budiman", "Darmawan", "Fauzi", "Halim", "Irawan", "Junaedi", "Kristanto", "Lubis",
            "Mulyadi", "Nasution", "Oktaviani", "Pangestu", "Rachman", "Sembiring", "Tanjung",
            "Usman", "Widodo", "Yusuf", "Zulkarnain", "Siregar", "Harahap", "Sitompul"]

# Jenis pelanggan: (porsi pelanggan, bobot frekuensi relatif, peluang member, peluang mahasiswa)
JENIS = {"komuter": (0.04, 25.0, 0.80, 0.35),
         "reguler": (0.21, 8.0, 0.45, 0.30),
         "jarang": (0.75, 1.0, 0.10, 0.25)}
JUMLAH_PELANGGAN = {"Solo-Semarang": 10_500, "Semarang-Tayu": 3_200, "Solo-Tayu": 2_300}
# Pengali peluang member per koridor agar porsi diskon mendekati laporan
# (Solo/Semarang ~3-6% dari pendapatan, Tayu ~2%).
FAKTOR_MEMBER = {"Solo-Semarang": 0.6, "Semarang-Tayu": 0.33, "Solo-Tayu": 0.33}


def buat_pelanggan() -> dict[str, pd.DataFrame]:
    total = sum(JUMLAH_PELANGGAN.values())
    nama = set()
    while len(nama) < total:
        n = f"{rng.choice(DEPAN)} {rng.choice(TENGAH)} {rng.choice(BELAKANG)}".replace("  ", " ")
        nama.add(n)
    nama = list(nama)
    rng.shuffle(nama)
    hari_total = (SELESAI - MULAI).days
    hasil, i = {}, 0
    for koridor, n in JUMLAH_PELANGGAN.items():
        jenis = rng.choice(list(JENIS), size=n, p=[v[0] for v in JENIS.values()])
        bobot = np.array([JENIS[j][1] for j in jenis]) * rng.lognormal(0, 0.4, n)
        # Masa aktif pelanggan: mulai & berhenti acak -> recency bervariasi.
        mulai = rng.integers(-200, hari_total - 30, n)
        lama = np.where(jenis == "komuter", rng.integers(300, 1400, n), rng.integers(60, 1300, n))
        akhir = np.minimum(mulai + lama, hari_total + 400)
        mulai = np.maximum(mulai, 0)
        member = rng.random(n) < np.array([JENIS[j][2] for j in jenis]) * FAKTOR_MEMBER[koridor]
        mhs = rng.random(n) < np.array([JENIS[j][3] for j in jenis])
        status = np.where(member, np.where(mhs, "Member Mahasiswa", "Member Umum"), "Non-Member")
        hasil[koridor] = pd.DataFrame({"nama": nama[i:i + n], "jenis": jenis, "bobot": bobot,
                                       "mulai": mulai, "akhir": akhir, "member": status})
        i += n
    return hasil


# ---------------------------------------------------------------------------- generator
def main():
    sekolah = libur_sekolah_set()
    pelanggan = buat_pelanggan()
    hari = [MULAI + timedelta(days=k) for k in range(1, (SELESAI - MULAI).days + 1)]
    hari = [MULAI] + hari
    faktor = np.array([FAKTOR_BULAN[d.month] * FAKTOR_HARI[d.weekday()] * faktor_tren(d)
                       * faktor_kalender(d, sekolah) for d in hari])
    # Kalibrasi: rata-rata faktor Jul-Agu 2026 = 1, sehingga pax/hari = angka RUTE pada periode itu.
    idx_kal = [i for i, d in enumerate(hari) if d >= date(2026, 7, 1)]
    faktor = faktor / faktor[idx_kal].mean()

    ukuran = rng.choice([1, 2, 3, 4], p=[0.78, 0.15, 0.05, 0.02], size=2_000_000)
    pos_ukuran = 0
    huruf = np.array(list(string.ascii_uppercase))
    kode_terpakai = set()
    baris = []
    hilang = 0

    for nama_rute, info in RUTE.items():
        asal, tujuan = nama_rute.split("->")
        koridor = info["koridor"]
        plg = pelanggan[koridor]
        jadwal = [(l, j) for l in ("Reguler", "VIP") for j in JADWAL[nama_rute][l]]
        armada_basis = ARMADA[asal]
        for i_hari, d in enumerate(hari):
            # Permintaan harian ~ Poisson-Gamma (variasi antar-hari realistis).
            lam = info["pax"] * faktor[i_hari] * rng.gamma(40, 1 / 40) / 1.31
            n_booking = rng.poisson(lam)
            if n_booking == 0:
                continue
            aktif = np.where((plg["mulai"].values <= i_hari) & (plg["akhir"].values >= i_hari))[0]
            w = plg["bobot"].values[aktif]
            pilih = rng.choice(aktif, size=n_booking, p=w / w.sum())
            sisa = {(l, j): KAPASITAS[l] for l, j in jadwal}
            # Satu armada per jadwal per hari, bergiliran dalam pool cabang asal.
            no_armada = {}
            for k, (l, j) in enumerate(jadwal):
                no_armada[(l, j)] = (k + i_hari) % armada_basis[l] + 1
            for p_idx in pilih:
                jml = int(ukuran[pos_ukuran]); pos_ukuran += 1
                layanan = "VIP" if rng.random() < PORSI_VIP[koridor] else "Reguler"
                jam_opsi = JADWAL[nama_rute][layanan]
                bj = np.array([BOBOT_JAM[j] for j in jam_opsi])
                jam = int(rng.choice(jam_opsi, p=bj / bj.sum()))
                # Penuh -> geser ke jadwal berikutnya (layanan sama, lalu layanan lain).
                urutan = ([(layanan, x) for x in jam_opsi if x >= jam]
                          + [(layanan, x) for x in jam_opsi if x < jam]
                          + [(lain, x) for lain in ("Reguler", "VIP") if lain != layanan
                             for x in JADWAL[nama_rute][lain]])
                slot = next((s for s in urutan if sisa[s] >= jml), None)
                if slot is None:
                    hilang += jml
                    continue
                sisa[slot] -= jml
                layanan, jam = slot
                status = plg["member"].values[p_idx]
                harga = tarif(koridor, layanan, d)
                disk = DISKON[status]
                th_app = 0.25 + 0.20 * min(1, max(0, (d - MULAI).days / 1095))
                channel = "Aplikasi" if rng.random() < th_app else "Outlet"
                while True:
                    kode = f"{info['kode']}{d:%y%m%d}{''.join(rng.choice(huruf, 5))}"
                    if kode not in kode_terpakai:
                        kode_terpakai.add(kode)
                        break
                baris.append((
                    kode, d.isoformat(), NAMA_HARI[d.weekday()], f"{jam:02d}:00", nama_rute,
                    asal, tujuan, layanan,
                    f"{KODE_CABANG[asal]}-{'VIP' if layanan == 'VIP' else 'REG'}-{no_armada[slot]}",
                    "Penumpang", "-", jml, "Orang", channel, status, harga, disk,
                    harga * jml, disk * jml, (harga - disk) * jml, "Lunas", plg["nama"].values[p_idx]))

    kolom = ["Kode Transaksi", "Tanggal", "Hari", "Jam Keberangkatan", "Rute", "Cabang Asal",
             "Cabang Tujuan", "Layanan", "Armada", "Jenis Transaksi", "Jenis Paket", "Jumlah Unit",
             "Satuan", "Channel Pemesanan", "Jenis Member", "Harga Satuan", "Diskon per Tiket",
             "Total Harga", "Total Diskon", "Total Bayar", "Keterangan", "Nama Pelanggan"]
    df = pd.DataFrame(baris, columns=kolom).sort_values(["Tanggal", "Jam Keberangkatan", "Rute"])
    keluar = ROOT / "data" / "kencana_transaksi_gabungan.csv"
    df.to_csv(keluar, index=False)
    print(f"Transaksi: {len(df):,} | penumpang: {df['Jumlah Unit'].sum():,} | "
          f"pelanggan unik: {df['Nama Pelanggan'].nunique():,} | penumpang tidak terangkut "
          f"(jadwal penuh): {hilang:,}")
    print(f"Disimpan ke {keluar}")


if __name__ == "__main__":
    main()
