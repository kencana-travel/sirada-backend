"""Persiapan database sebelum server dijalankan (dipakai sebagai langkah awal start command
di Railway). Aman dijalankan berulang kali:

1. Migrasi skema (buat tabel / tambah kolom yang belum ada).
2. Muat data dari CSV bila transaksi masih kosong ATAU belum lengkap (mis. pemuatan
   sebelumnya terputus di tengah jalan) — data referensi & transaksi dihapus dulu lalu
   dimuat ulang dari awal. Akun pengguna tidak disentuh.
3. Bila belum ada akun sama sekali: buat akun awal (lihat app.seed_users).

Jalankan: python -m app.bootstrap"""
import os
import sys
import time
from pathlib import Path
from sqlalchemy import func
from app.core.database import SessionLocal
from app.core.migrate import jalankan_migrasi
from app.models.models import Armada, Cabang, Jadwal, JenisPaket, Member, Pengguna, Rute, Transaksi

CSV_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "kencana_transaksi_gabungan.csv"


def _jumlah_baris_csv(path: Path) -> int:
    with open(path, "rb") as f:
        return sum(1 for _ in f) - 1  # tanpa header


def _hapus_data_referensi() -> None:
    """Kosongkan tabel data (urutan mengikuti foreign key). Akun pengguna dipertahankan,
    tapi relasinya ke cabang dilepas karena tabel cabang ikut dibuat ulang."""
    db = SessionLocal()
    try:
        db.query(Pengguna).update({Pengguna.id_cabang: None}, synchronize_session=False)
        for model in (Transaksi, Jadwal, Armada, Rute, Member, JenisPaket, Cabang):
            db.query(model).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def main() -> None:
    print("[bootstrap] Migrasi skema...", flush=True)
    jalankan_migrasi()

    csv_path = Path(os.getenv("DATA_CSV_PATH", CSV_DEFAULT))
    if not csv_path.exists():
        sys.exit(f"[bootstrap] CSV tidak ditemukan: {csv_path}")
    target = _jumlah_baris_csv(csv_path)

    db = SessionLocal()
    try:
        jumlah = db.query(func.count(Transaksi.id_transaksi)).scalar() or 0
    finally:
        db.close()

    if jumlah >= target:
        print(f"[bootstrap] Data transaksi lengkap ({jumlah:,} baris), lewati pemuatan CSV.", flush=True)
    else:
        if jumlah > 0:
            print(f"[bootstrap] Data transaksi TIDAK lengkap ({jumlah:,} dari {target:,} baris) — "
                  "kemungkinan pemuatan sebelumnya terputus. Menghapus dan memuat ulang...", flush=True)
            _hapus_data_referensi()
        print(f"[bootstrap] Memuat {target:,} baris dari {csv_path.name} (beberapa menit)...", flush=True)
        mulai = time.time()
        from app.load_data import main as load_data
        load_data(str(csv_path), reset=False)
        print(f"[bootstrap] Data dimuat dalam {time.time() - mulai:.0f} detik.", flush=True)

    from app.seed_users import seed
    seed()
    print("[bootstrap] Selesai.", flush=True)


if __name__ == "__main__":
    main()
