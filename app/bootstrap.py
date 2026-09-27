"""Persiapan database sebelum server dijalankan (dipakai sebagai langkah awal start command
di Railway). Aman dijalankan berulang kali:

1. Migrasi skema (buat tabel / tambah kolom yang belum ada).
2. Bila tabel transaksi masih kosong (deploy pertama): muat data dari CSV.
3. Bila belum ada akun sama sekali: buat akun awal (lihat app.seed_users).

Jalankan: python -m app.bootstrap"""
import os
import sys
import time
from pathlib import Path
from app.core.database import SessionLocal
from app.core.migrate import jalankan_migrasi
from app.models.models import Transaksi

CSV_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "kencana_transaksi_gabungan.csv"


def main() -> None:
    print("[bootstrap] Migrasi skema...", flush=True)
    jalankan_migrasi()

    db = SessionLocal()
    try:
        ada_transaksi = db.query(Transaksi.id_transaksi).first() is not None
    finally:
        db.close()

    if ada_transaksi:
        print("[bootstrap] Data transaksi sudah ada, lewati pemuatan CSV.", flush=True)
    else:
        csv_path = Path(os.getenv("DATA_CSV_PATH", CSV_DEFAULT))
        if not csv_path.exists():
            sys.exit(f"[bootstrap] Database kosong dan CSV tidak ditemukan: {csv_path}")
        print(f"[bootstrap] Database kosong — memuat data dari {csv_path.name} (beberapa menit)...", flush=True)
        mulai = time.time()
        from app.load_data import main as load_data
        load_data(str(csv_path), reset=False)
        print(f"[bootstrap] Data dimuat dalam {time.time() - mulai:.0f} detik.", flush=True)

    from app.seed_users import seed
    seed()
    print("[bootstrap] Selesai.", flush=True)


if __name__ == "__main__":
    main()
